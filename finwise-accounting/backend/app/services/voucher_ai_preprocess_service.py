from __future__ import annotations

import json
import re
import time
from decimal import Decimal
from typing import Protocol
from urllib import error, request
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.org_context import get_current_organization_id
from app.models import (
    AuditLog,
    BankTransaction,
    DEFAULT_CHANNEL_ID,
    Enterprise,
    Invoice,
    MatchRecord,
    MonthlyWorkPackage,
    Voucher,
    VoucherRule,
)
from app.services.voucher_service import VoucherDomainError, generate_voucher_drafts


VALID_TASK_TYPES = {"FULL_MATCH", "DIFFERENCE_COMPLETION", "SINGLE_SOURCE", "HISTORICAL_REVIEW"}
SUMMARY_CATEGORY_KEYWORDS = {
    "电子转账": ("电子转账", "网银", "转账", "银企"),
    "手续费": ("手续费", "工本费"),
    "工资": ("工资", "薪资", "社保", "公积金"),
    "税费": ("税费", "税款", "增值税", "所得税", "附加税", "印花税"),
    "利息": ("利息", "结息"),
    "服务费": ("服务费", "咨询费", "技术服务"),
    "货款": ("货款", "销售款", "采购款", "收款", "付款"),
    "房租": ("房租", "租金", "租赁"),
}
INDUSTRY_CATEGORY_KEYWORDS = {
    "制造业": ("制造", "生产", "加工"),
    "服务业": ("服务", "咨询"),
    "批发零售": ("批发", "零售", "商贸"),
    "建筑业": ("建筑", "工程", "施工"),
    "科技": ("科技", "软件", "信息技术"),
    "物流": ("物流", "运输", "货运"),
    "餐饮": ("餐饮", "食品"),
}
POST_GENERATION_ERROR_SUMMARY = "POST_GENERATION_PERSISTENCE_FAILED"
POST_GENERATION_OPERATOR_MESSAGE = "生成结果保存失败"

VOUCHER_PREPROCESS_SYSTEM_PROMPT = (
    "你是代账公司的凭证预处理助手。只能根据脱敏后的金额、日期、方向、摘要关键词、发票方向、税额、"
    "对方别名和历史规则判断。不要输出企业全称、税号、银行账号或完整发票号。先完整比对全部流水和发票，"
    "但只返回最需要人工关注或最能代表处理规则的重点建议，task_suggestions 最多 30 条。返回 JSON，格式为 "
    '{"analysis_summary":"中文概括，说明已比对范围、主要处理策略和需人工关注点",'
    '"task_suggestions":[{"source_key":"string","task_type":"FULL_MATCH|DIFFERENCE_COMPLETION|'
    'SINGLE_SOURCE|HISTORICAL_REVIEW","confidence":0-100,"summary":"中文凭证摘要",'
    '"reason":"中文原因","bank_refs":["T001"],"invoice_refs":["I001"],'
    '"entries":[{"direction":"DEBIT|CREDIT","account_code":"1002","account_name":"银行存款",'
    '"amount":100.00}]}]}。不确定的任务 confidence 低于 80，并说明需要人工确认。'
)


class VoucherAiPreprocessUnavailableError(Exception):
    def __init__(self, message: str, *, used_kimi: bool = True):
        super().__init__(message)
        self.used_kimi = used_kimi


class VoucherAiPreprocessFailedError(Exception):
    def __init__(self, message: str, audit: dict):
        super().__init__(message)
        self.audit = audit


class VoucherPreprocessClient(Protocol):
    def propose_voucher_tasks(self, payload: dict) -> dict:
        ...


class MoonshotVoucherPreprocessClient:
    def __init__(self, *, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def propose_voucher_tasks(self, payload: dict) -> dict:
        if not self.api_key:
            raise VoucherAiPreprocessUnavailableError("Moonshot API key is not configured.", used_kimi=False)

        body = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "temperature": _temperature_for_model(self.model),
            "max_tokens": 4000,
            "messages": [
                {"role": "system", "content": VOUCHER_PREPROCESS_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        http_request = request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=90) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            return json.loads(response_data["choices"][0]["message"]["content"])
        except TimeoutError as exc:
            raise VoucherAiPreprocessUnavailableError("AI 服务响应超时", used_kimi=True) from exc
        except error.HTTPError as exc:
            raise VoucherAiPreprocessUnavailableError(f"AI 服务返回错误：HTTP {exc.code}", used_kimi=True) from exc
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise VoucherAiPreprocessUnavailableError("AI 服务暂时不可用", used_kimi=True) from exc


def create_default_voucher_preprocess_client() -> VoucherPreprocessClient:
    settings = get_settings()
    return MoonshotVoucherPreprocessClient(
        api_key=settings.moonshot_api_key,
        base_url=settings.moonshot_base_url,
        model=settings.moonshot_model,
    )


def _temperature_for_model(model: str) -> float:
    if model.strip().lower() == "kimi-k2.6":
        return 1
    return 0.2


def run_voucher_ai_preprocessing(
    db: Session,
    *,
    monthly_work_package_id: UUID,
    ai_client: VoucherPreprocessClient | None = None,
) -> dict:
    started_at = time.monotonic()
    organization_id = get_current_organization_id()
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None or package.organization_id != organization_id:
        raise VoucherDomainError("Monthly work package not found in current organization.")

    enterprise = db.get(Enterprise, package.enterprise_id)
    if enterprise is None or enterprise.organization_id != organization_id:
        raise VoucherDomainError("Enterprise not found.")

    payload = build_voucher_preprocess_payload(db, package=package, enterprise=enterprise)
    settings = get_settings()
    client = ai_client or create_default_voucher_preprocess_client()
    try:
        ai_response = client.propose_voucher_tasks(payload)
        normalized_ai = _normalize_ai_response(ai_response, payload_ref_index=_payload_ref_index(payload))
        normalized_suggestions = normalized_ai["task_suggestions"]
    except VoucherAiPreprocessUnavailableError as exc:
        audit = _build_audit(
            started_at=started_at,
            payload=payload,
            model=settings.moonshot_model,
            used_kimi=exc.used_kimi,
            ai_status="FAILED",
            created_vouchers=0,
            generated_task_counts={},
            error_summary=str(exc),
        )
        _write_audit_log(db, package=package, audit=audit)
        db.commit()
        raise VoucherAiPreprocessFailedError(f"AI 预处理失败：{audit['error_summary']}", audit) from exc

    generated = generate_voucher_drafts(db, monthly_work_package_id=package.id)
    vouchers = generated["vouchers"]
    created_voucher_ids = [voucher.id for voucher in vouchers]
    try:
        source_ref_index = _source_ref_index(db, package=package)
        _attach_preprocess_metadata(vouchers, suggestions=normalized_suggestions, source_ref_index=source_ref_index, ai_status="SUCCESS")

        audit = _build_audit(
            started_at=started_at,
            payload=payload,
            model=settings.moonshot_model,
            used_kimi=True,
            ai_status="SUCCESS",
            created_vouchers=generated["created_vouchers"],
            generated_task_counts=_task_counts(vouchers),
            error_summary="",
            analysis_summary=normalized_ai["analysis_summary"],
            suggestion_count=len(normalized_suggestions),
        )
        _write_audit_log(db, package=package, audit=audit)
        db.commit()
    except Exception as exc:
        _cleanup_created_vouchers(db, voucher_ids=created_voucher_ids)
        audit = _build_audit(
            started_at=started_at,
            payload=payload,
            model=settings.moonshot_model,
            used_kimi=True,
            ai_status="FAILED",
            created_vouchers=0,
            generated_task_counts={},
            error_summary=POST_GENERATION_ERROR_SUMMARY,
        )
        _write_audit_log(db, package=package, audit=audit)
        db.commit()
        raise VoucherAiPreprocessFailedError(f"AI 预处理失败：{POST_GENERATION_OPERATOR_MESSAGE}", audit) from exc

    return {
        "ai_status": "SUCCESS",
        "used_kimi": True,
        "message": "AI 预处理完成",
        "created_vouchers": generated["created_vouchers"],
        "vouchers": vouchers,
        "audit": audit,
    }


def build_voucher_preprocess_payload(db: Session, *, package: MonthlyWorkPackage, enterprise: Enterprise | None) -> dict:
    transactions = list(
        db.scalars(
            select(BankTransaction)
            .where(
                BankTransaction.organization_id == package.organization_id,
                BankTransaction.monthly_work_package_id == package.id,
            )
            .order_by(BankTransaction.transaction_date, BankTransaction.id)
        )
    )
    invoices = list(
        db.scalars(
            select(Invoice)
            .where(
                Invoice.organization_id == package.organization_id,
                Invoice.monthly_work_package_id == package.id,
            )
            .order_by(Invoice.invoice_date, Invoice.id)
        )
    )
    matches = list(
        db.scalars(
            select(MatchRecord)
            .where(
                MatchRecord.organization_id == package.organization_id,
                MatchRecord.monthly_work_package_id == package.id,
            )
            .order_by(MatchRecord.created_at, MatchRecord.id)
        )
    )
    rules = list(
        db.scalars(
            select(VoucherRule)
            .where(
                VoucherRule.organization_id == package.organization_id,
                VoucherRule.enterprise_id == package.enterprise_id,
            )
            .order_by(VoucherRule.created_at.desc(), VoucherRule.id)
            .limit(20)
        )
    )
    party_aliases: dict[str, str] = {}
    transaction_refs = {item.id: f"T{index:03d}" for index, item in enumerate(transactions, start=1)}
    invoice_refs = {item.id: f"I{index:03d}" for index, item in enumerate(invoices, start=1)}
    enterprise_name = enterprise.name if enterprise else ""
    return {
        "package": {
            "period": f"{package.period_year}-{package.period_month:02d}",
            "enterprise_alias": "企业主体",
            "industry_categories": _safe_industry_categories(enterprise.industry if enterprise else ""),
        },
        "bank_transactions": [
            {
                "ref": transaction_refs[item.id],
                "date": item.transaction_date.isoformat(),
                "direction": "RECEIPT" if _money(item.credit_amount) > 0 else "PAYMENT",
                "amount": str(abs(_money(item.credit_amount) - _money(item.debit_amount))),
                "counterparty_alias": _alias_for(item.counterparty_name or "", party_aliases, prefix="交易对方"),
                "summary_keywords": _safe_summary_keywords(item.summary),
            }
            for item in transactions
        ],
        "invoices": [
            {
                "ref": invoice_refs[item.id],
                "date": item.invoice_date.isoformat(),
                "direction": item.invoice_direction,
                "amount": str(_money(item.amount)),
                "tax_amount": str(_money(item.tax_amount)),
                "total_amount": str(_money(item.total_amount)),
                "counterparty_alias": _alias_for(
                    _invoice_counterparty_name(item, enterprise_name=enterprise_name),
                    party_aliases,
                    prefix="交易对方",
                ),
            }
            for item in invoices
        ],
        "matched_records": [
            {
                "bank_ref": transaction_refs.get(item.bank_transaction_id),
                "invoice_ref": invoice_refs.get(item.invoice_id),
                "confidence": item.confidence,
                "status": item.confirmation_status,
                "method": item.match_method,
            }
            for item in matches
            if item.bank_transaction_id in transaction_refs and item.invoice_id in invoice_refs
        ],
        "historical_rules": [
            {
                "rule_alias": f"R{index:03d}",
                "treatment_type": _safe_summary_keywords(item.summary_template),
                "summary_keywords": _safe_summary_keywords(" ".join(str(keyword) for keyword in (item.summary_keywords or []))),
                "counterparty_alias": _alias_for(item.counterparty_pattern or "", party_aliases, prefix="交易对方")
                if item.counterparty_pattern
                else "",
                "source_direction": item.source_direction or "",
                "invoice_direction": item.invoice_direction or "",
                "debit_account_code": item.debit_account_code,
                "credit_account_code": item.credit_account_code,
            }
            for index, item in enumerate(rules, start=1)
        ],
    }


def _build_audit(
    *,
    started_at: float,
    payload: dict,
    model: str,
    used_kimi: bool,
    ai_status: str,
    created_vouchers: int,
    generated_task_counts: dict,
    error_summary: str,
    analysis_summary: str = "",
    suggestion_count: int = 0,
) -> dict:
    return {
        "used_kimi": used_kimi,
        "ai_status": ai_status,
        "model": model,
        "input_bank_count": len(payload["bank_transactions"]),
        "input_invoice_count": len(payload["invoices"]),
        "generated_task_counts": generated_task_counts,
        "created_vouchers": created_vouchers,
        "duration_ms": int((time.monotonic() - started_at) * 1000),
        "error_summary": error_summary,
        "analysis_summary": analysis_summary,
        "suggestion_count": suggestion_count,
    }


def _write_audit_log(db: Session, *, package: MonthlyWorkPackage, audit: dict) -> None:
    db.add(
        AuditLog(
            channel_id=DEFAULT_CHANNEL_ID,
            organization_id=package.organization_id,
            monthly_work_package_id=package.id,
            actor="system",
            action="VOUCHER_AI_PREPROCESS",
            before_data={
                "payload_summary": {
                    "bank_transactions": audit["input_bank_count"],
                    "invoices": audit["input_invoice_count"],
                }
            },
            after_data=audit,
        )
    )


def _money(value) -> Decimal:
    return Decimal(str(value or "0")).quantize(Decimal("0.01"))


def _safe_words(text: str) -> str:
    text = re.sub(r"[A-Za-z0-9]{6,}", "[REDACTED]", str(text or ""))
    return " ".join(text.replace("\n", " ").split())[:80]


def _safe_summary_keywords(text: str) -> list[str]:
    redacted = _safe_words(text)
    categories = [
        category
        for category, keywords in SUMMARY_CATEGORY_KEYWORDS.items()
        if any(keyword in redacted for keyword in keywords)
    ]
    return categories or ["其他"]


def _safe_industry_categories(text: str) -> list[str]:
    redacted = _safe_words(text)
    categories = [
        category
        for category, keywords in INDUSTRY_CATEGORY_KEYWORDS.items()
        if any(keyword in redacted for keyword in keywords)
    ]
    return categories or ["未分类"]


def _alias_for(name: str, aliases: dict[str, str], *, prefix: str) -> str:
    key = _safe_words(name) or "空白对方"
    if key not in aliases:
        aliases[key] = f"{prefix}{len(aliases) + 1}"
    return aliases[key]


def _invoice_counterparty_name(invoice: Invoice, *, enterprise_name: str) -> str:
    if invoice.invoice_direction == "OUTPUT":
        return invoice.buyer_name if invoice.buyer_name != enterprise_name else invoice.seller_name
    return invoice.seller_name if invoice.seller_name != enterprise_name else invoice.buyer_name


def _task_counts(vouchers: list[Voucher]) -> dict:
    counts: dict[str, int] = {}
    for voucher in vouchers:
        task_type = str((voucher.source_data or {}).get("voucher_task_type") or "UNKNOWN")
        counts[task_type] = counts.get(task_type, 0) + 1
    return counts


def _normalize_ai_response(ai_response: dict, *, payload_ref_index: dict[str, set[str]]) -> dict:
    if not isinstance(ai_response, dict):
        raise VoucherAiPreprocessUnavailableError("AI 返回格式无效")
    suggestions = ai_response.get("task_suggestions")
    analysis_summary = str(ai_response.get("analysis_summary") or "").strip()
    if not isinstance(suggestions, list) or not suggestions:
        raise VoucherAiPreprocessUnavailableError("AI 未返回有效预处理建议")
    if not analysis_summary:
        analysis_summary = "AI 已完成流水与发票比对，并返回凭证处理建议。"

    normalized = []
    for index, suggestion in enumerate(suggestions, start=1):
        if not isinstance(suggestion, dict):
            raise VoucherAiPreprocessUnavailableError(f"AI 建议 {index} 格式无效")
        task_type = str(suggestion.get("task_type") or "")
        if task_type not in VALID_TASK_TYPES:
            raise VoucherAiPreprocessUnavailableError(f"AI 建议 {index} 任务类型无效")
        confidence = suggestion.get("confidence")
        if not isinstance(confidence, int) or confidence < 0 or confidence > 100:
            raise VoucherAiPreprocessUnavailableError(f"AI 建议 {index} 置信度无效")
        normalized.append(
            {
                "source_key": str(suggestion.get("source_key") or ""),
                "task_type": task_type,
                "confidence": confidence,
                "summary": str(suggestion.get("summary") or ""),
                "reason": str(suggestion.get("reason") or ""),
                "bank_refs": _normalize_ref_list(suggestion.get("bank_refs"), valid_refs=payload_ref_index["bank"], ref_label="bank_refs"),
                "invoice_refs": _normalize_ref_list(
                    suggestion.get("invoice_refs"),
                    valid_refs=payload_ref_index["invoice"],
                    ref_label="invoice_refs",
                ),
                "entries": suggestion.get("entries") if isinstance(suggestion.get("entries"), list) else [],
            }
        )
    return {"analysis_summary": analysis_summary[:500], "task_suggestions": normalized}


def _payload_ref_index(payload: dict) -> dict[str, set[str]]:
    return {
        "bank": {str(item.get("ref")) for item in payload.get("bank_transactions", []) if item.get("ref")},
        "invoice": {str(item.get("ref")) for item in payload.get("invoices", []) if item.get("ref")},
    }


def _normalize_ref_list(value, *, valid_refs: set[str], ref_label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise VoucherAiPreprocessUnavailableError("AI 建议来源引用格式无效")
    refs = [str(item) for item in value if str(item or "").strip()]
    unknown_refs = sorted(ref for ref in refs if ref not in valid_refs)
    if unknown_refs:
        raise VoucherAiPreprocessUnavailableError(f"AI 建议包含未知来源引用：{ref_label}={','.join(unknown_refs)}")
    return refs


def _cleanup_created_vouchers(db: Session, *, voucher_ids: list[UUID]) -> None:
    db.rollback()
    for voucher_id in voucher_ids:
        voucher = db.get(Voucher, voucher_id)
        if voucher is not None:
            db.delete(voucher)
    db.flush()


def _source_ref_index(db: Session, *, package: MonthlyWorkPackage) -> dict[str, dict[str, UUID]]:
    transactions = list(
        db.scalars(
            select(BankTransaction)
            .where(
                BankTransaction.organization_id == package.organization_id,
                BankTransaction.monthly_work_package_id == package.id,
            )
            .order_by(BankTransaction.transaction_date, BankTransaction.id)
        )
    )
    invoices = list(
        db.scalars(
            select(Invoice)
            .where(
                Invoice.organization_id == package.organization_id,
                Invoice.monthly_work_package_id == package.id,
            )
            .order_by(Invoice.invoice_date, Invoice.id)
        )
    )
    return {
        "bank": {f"T{index:03d}": item.id for index, item in enumerate(transactions, start=1)},
        "invoice": {f"I{index:03d}": item.id for index, item in enumerate(invoices, start=1)},
    }


def _attach_preprocess_metadata(
    vouchers: list[Voucher],
    *,
    suggestions: list[dict],
    source_ref_index: dict[str, dict[str, UUID]],
    ai_status: str,
) -> None:
    for voucher in vouchers:
        source_data = dict(voucher.source_data or {})
        suggestion = _matching_suggestion(source_data, voucher_source_key=voucher.source_key, suggestions=suggestions, source_ref_index=source_ref_index)
        source_data["ai_preprocess"] = {
            "ai_status": ai_status,
            "kimi_suggestion": suggestion or {},
        }
        if suggestion and suggestion.get("reason"):
            voucher.ai_reason = str(suggestion["reason"])
        if suggestion and suggestion.get("confidence") is not None:
            voucher.ai_confidence = max(0, min(100, int(suggestion["confidence"])))
        voucher.source_data = source_data


def _matching_suggestion(
    source_data: dict,
    *,
    voucher_source_key: str,
    suggestions: list[dict],
    source_ref_index: dict[str, dict[str, UUID]],
) -> dict | None:
    for suggestion in suggestions:
        if suggestion.get("source_key") and suggestion["source_key"] == voucher_source_key:
            return suggestion

    voucher_bank_ids = {str(item) for item in _source_values(source_data, singular="bank_transaction_id", plural="bank_transaction_ids")}
    voucher_invoice_ids = {str(item) for item in _source_values(source_data, singular="invoice_id", plural="invoice_ids")}
    for suggestion in suggestions:
        bank_ids = {str(source_ref_index["bank"].get(ref)) for ref in suggestion.get("bank_refs", []) if source_ref_index["bank"].get(ref)}
        invoice_ids = {
            str(source_ref_index["invoice"].get(ref))
            for ref in suggestion.get("invoice_refs", [])
            if source_ref_index["invoice"].get(ref)
        }
        if bank_ids and invoice_ids and bank_ids == voucher_bank_ids and invoice_ids == voucher_invoice_ids:
            return suggestion
        if bank_ids and not invoice_ids and bank_ids == voucher_bank_ids:
            return suggestion
        if invoice_ids and not bank_ids and invoice_ids == voucher_invoice_ids:
            return suggestion
    return None


def _source_values(source_data: dict, *, singular: str, plural: str) -> list[str]:
    if source_data.get(plural):
        value = source_data[plural]
        return [str(item) for item in value] if isinstance(value, list) else [str(value)]
    if source_data.get(singular):
        return [str(source_data[singular])]
    return []
