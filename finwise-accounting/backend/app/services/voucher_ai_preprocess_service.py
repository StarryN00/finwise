from __future__ import annotations

import json
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


VOUCHER_PREPROCESS_SYSTEM_PROMPT = (
    "你是代账公司的凭证预处理助手。只能根据脱敏后的金额、日期、方向、摘要关键词、发票方向、税额、"
    "对方别名和历史规则判断。不要输出企业全称、税号、银行账号或完整发票号。返回 JSON，格式为 "
    '{"task_suggestions":[{"source_key":"string","task_type":"FULL_MATCH|DIFFERENCE_COMPLETION|'
    'SINGLE_SOURCE|HISTORICAL_REVIEW","confidence":0-100,"summary":"中文凭证摘要",'
    '"reason":"中文原因","bank_refs":["T001"],"invoice_refs":["I001"],'
    '"entries":[{"direction":"DEBIT|CREDIT","account_code":"1002","account_name":"银行存款",'
    '"amount":100.00}]}]}。不确定的任务 confidence 低于 80，并说明需要人工确认。'
)


class VoucherAiPreprocessUnavailableError(Exception):
    pass


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
            raise VoucherAiPreprocessUnavailableError("Moonshot API key is not configured.")

        body = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
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
            raise VoucherAiPreprocessUnavailableError("AI 服务响应超时") from exc
        except error.HTTPError as exc:
            raise VoucherAiPreprocessUnavailableError(f"AI 服务返回错误：HTTP {exc.code}") from exc
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise VoucherAiPreprocessUnavailableError("AI 服务暂时不可用") from exc


def create_default_voucher_preprocess_client() -> VoucherPreprocessClient:
    settings = get_settings()
    return MoonshotVoucherPreprocessClient(
        api_key=settings.moonshot_api_key,
        base_url=settings.moonshot_base_url,
        model=settings.moonshot_model,
    )


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
    except VoucherAiPreprocessUnavailableError as exc:
        audit = _build_audit(
            started_at=started_at,
            payload=payload,
            model=settings.moonshot_model,
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
    _attach_preprocess_metadata(vouchers, ai_response=ai_response, ai_status="SUCCESS")

    audit = _build_audit(
        started_at=started_at,
        payload=payload,
        model=settings.moonshot_model,
        ai_status="SUCCESS",
        created_vouchers=generated["created_vouchers"],
        generated_task_counts=_task_counts(vouchers),
        error_summary="",
    )
    _write_audit_log(db, package=package, audit=audit)
    db.commit()
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
            "industry": enterprise.industry if enterprise else "",
        },
        "bank_transactions": [
            {
                "ref": transaction_refs[item.id],
                "date": item.transaction_date.isoformat(),
                "direction": "RECEIPT" if _money(item.credit_amount) > 0 else "PAYMENT",
                "amount": str(abs(_money(item.credit_amount) - _money(item.debit_amount))),
                "counterparty_alias": _alias_for(item.counterparty_name or "", party_aliases, prefix="交易对方"),
                "summary_keywords": _safe_words(item.summary),
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
                "scope": item.scope,
                "summary_keywords": item.summary_keywords or [],
                "counterparty_alias": _alias_for(item.counterparty_pattern or "", party_aliases, prefix="交易对方")
                if item.counterparty_pattern
                else "",
                "invoice_direction": item.invoice_direction or "",
                "suggested_business_type": item.suggested_business_type,
            }
            for item in rules
        ],
    }


def _build_audit(
    *,
    started_at: float,
    payload: dict,
    model: str,
    ai_status: str,
    created_vouchers: int,
    generated_task_counts: dict,
    error_summary: str,
) -> dict:
    return {
        "used_kimi": True,
        "ai_status": ai_status,
        "model": model,
        "input_bank_count": len(payload["bank_transactions"]),
        "input_invoice_count": len(payload["invoices"]),
        "generated_task_counts": generated_task_counts,
        "created_vouchers": created_vouchers,
        "duration_ms": int((time.monotonic() - started_at) * 1000),
        "error_summary": error_summary,
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
    return " ".join(str(text or "").replace("\n", " ").split())[:80]


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


def _attach_preprocess_metadata(vouchers: list[Voucher], *, ai_response: dict, ai_status: str) -> None:
    suggestions = ai_response.get("task_suggestions") if isinstance(ai_response, dict) else []
    suggestion_by_type = {
        str(item.get("task_type")): item
        for item in suggestions or []
        if isinstance(item, dict) and item.get("task_type")
    }
    for voucher in vouchers:
        source_data = dict(voucher.source_data or {})
        task_type = str(source_data.get("voucher_task_type") or "")
        suggestion = suggestion_by_type.get(task_type)
        source_data["ai_preprocess"] = {
            "ai_status": ai_status,
            "kimi_suggestion": suggestion or {},
        }
        if suggestion and suggestion.get("reason"):
            voucher.ai_reason = str(suggestion["reason"])
        if suggestion and suggestion.get("confidence") is not None:
            voucher.ai_confidence = max(0, min(100, int(suggestion["confidence"])))
        voucher.source_data = source_data
