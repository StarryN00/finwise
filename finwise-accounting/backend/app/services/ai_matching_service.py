from __future__ import annotations

import json
from decimal import Decimal
from typing import Protocol
from urllib import error, request
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AccountingLine, BankTransaction, Enterprise, Invoice, MatchRecord, MonthlyWorkPackage
from app.services.matching_service import MonthlyPackageNotFoundError, refresh_package_matching_summary


AI_PAYLOAD_MAX_TRANSACTIONS = 32
AI_PAYLOAD_MAX_INVOICES = 48
AI_TEXT_LIMIT = 80


class AiMatchingUnavailableError(Exception):
    pass


class AiMatchingClient(Protocol):
    def propose_matches(self, payload: dict) -> dict:
        ...


class MoonshotAiMatchingClient:
    def __init__(self, *, api_key: str, base_url: str, model: str, timeout_seconds: int = 240):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def propose_matches(self, payload: dict) -> dict:
        if not self.api_key:
            raise AiMatchingUnavailableError("Moonshot API key is not configured.")

        body = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是代账业务的流水发票匹配助手。只根据脱敏后的金额、日期、方向、主体别名、摘要和备注判断。"
                        "返回 JSON，格式为 {\"matches\":[{\"transaction_ref\":\"T001\",\"invoice_ref\":\"I001\","
                        "\"confidence\":0-100,\"explanation\":\"简短原因\"}]}。不确定的匹配 confidence 低于 90。"
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        http_request = request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            content = response_data["choices"][0]["message"]["content"]
            return json.loads(content)
        except TimeoutError as exc:
            raise AiMatchingUnavailableError("AI 服务响应超时，请稍后重试，或先使用规则匹配。") from exc
        except error.HTTPError as exc:
            raise AiMatchingUnavailableError(f"AI 服务返回错误：HTTP {exc.code}") from exc
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise AiMatchingUnavailableError("AI 服务暂时不可用，请稍后重试。") from exc


def run_ai_matching(db: Session, *, monthly_work_package_id: UUID, ai_client: AiMatchingClient | None = None) -> dict:
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None:
        raise MonthlyPackageNotFoundError("Monthly work package not found.")

    enterprise = db.get(Enterprise, package.enterprise_id)
    enterprise_name = enterprise.name if enterprise else ""
    transactions = _candidate_transactions(db, package.id)
    invoices = _candidate_invoices(db, package.id)
    payload, transaction_by_ref, invoice_by_ref = _build_ai_payload(
        transactions=transactions,
        invoices=invoices,
        enterprise_name=enterprise_name,
    )
    if not payload["bank_transactions"] or not payload["invoices"]:
        refresh_package_matching_summary(db, monthly_work_package_id=package.id)
        db.commit()
        return {"created_matches": 0, "uncertain_matches": 0, "candidate_transactions": len(transactions), "candidate_invoices": len(invoices)}

    settings = get_settings()
    client = ai_client or MoonshotAiMatchingClient(
        api_key=settings.moonshot_api_key,
        base_url=settings.moonshot_base_url,
        model=settings.moonshot_model,
        timeout_seconds=settings.moonshot_timeout_seconds,
    )
    threshold = settings.ai_match_confidence_threshold
    existing_pairs = _existing_match_pairs(db, package.id)
    try:
        ai_response = client.propose_matches(payload)
    except AiMatchingUnavailableError:
        created_matches = _create_local_fallback_matches(
            db,
            package=package,
            transactions=transactions,
            invoices=invoices,
            existing_pairs=existing_pairs,
        )
        pending_confirmations = refresh_package_matching_summary(db, monthly_work_package_id=package.id)
        db.commit()
        return {
            "aiStatus": "FALLBACK",
            "message": "AI 响应超时，已用本地候选规则生成待确认建议。",
            "created_matches": created_matches,
            "uncertain_matches": 0,
            "candidate_transactions": len(transactions),
            "candidate_invoices": len(invoices),
            "pending_confirmations": pending_confirmations,
        }

    created_matches = 0
    uncertain_matches = 0
    used_transaction_ids: set[UUID] = set()
    used_invoice_ids: set[UUID] = set()

    for suggestion in ai_response.get("matches", []):
        transaction = transaction_by_ref.get(str(suggestion.get("transaction_ref", "")))
        invoice = invoice_by_ref.get(str(suggestion.get("invoice_ref", "")))
        if transaction is None or invoice is None:
            continue
        if transaction.id in used_transaction_ids or invoice.id in used_invoice_ids:
            continue
        confidence = int(suggestion.get("confidence") or 0)
        if confidence < threshold:
            uncertain_matches += 1
            continue
        if (transaction.id, invoice.id) in existing_pairs:
            continue
        db.add(
            MatchRecord(
                organization_id=package.organization_id,
                monthly_work_package_id=package.id,
                bank_transaction_id=transaction.id,
                invoice_id=invoice.id,
                match_method="AI_SUGGESTED",
                confidence=confidence,
                explanation=str(suggestion.get("explanation") or "AI 建议匹配"),
                confirmation_status="PENDING",
            )
        )
        existing_pairs.add((transaction.id, invoice.id))
        used_transaction_ids.add(transaction.id)
        used_invoice_ids.add(invoice.id)
        created_matches += 1

    pending_confirmations = refresh_package_matching_summary(db, monthly_work_package_id=package.id)
    db.commit()
    return {
        "created_matches": created_matches,
        "uncertain_matches": uncertain_matches,
        "candidate_transactions": len(transactions),
        "candidate_invoices": len(invoices),
        "pending_confirmations": pending_confirmations,
    }


def _create_local_fallback_matches(
    db: Session,
    *,
    package: MonthlyWorkPackage,
    transactions: list[BankTransaction],
    invoices: list[Invoice],
    existing_pairs: set[tuple[UUID, UUID]],
) -> int:
    candidates = []
    for transaction in transactions:
        for invoice in invoices:
            score = _candidate_score(transaction, invoice)
            if score is None:
                continue
            amount_gap, date_gap, party_penalty = score
            allowed_fallback_gap = max(Decimal("10.00"), abs(_transaction_amount(transaction)) * Decimal("0.02"))
            if amount_gap > allowed_fallback_gap or date_gap > 15:
                continue
            candidates.append((score, transaction, invoice, "AI_FALLBACK_RULE"))

    if not candidates:
        for transaction in transactions:
            for invoice in invoices:
                score = _candidate_score(transaction, invoice, broad=True)
                if score is None:
                    continue
                candidates.append((score, transaction, invoice, "AI_FALLBACK_CANDIDATE"))
    candidates.sort(key=lambda item: item[0])

    created_matches = 0
    used_transaction_ids: set[UUID] = set()
    used_invoice_ids: set[UUID] = set()
    for score, transaction, invoice, match_method in candidates:
        if transaction.id in used_transaction_ids or invoice.id in used_invoice_ids:
            continue
        if (transaction.id, invoice.id) in existing_pairs:
            continue
        db.add(
            MatchRecord(
                organization_id=package.organization_id,
                monthly_work_package_id=package.id,
                bank_transaction_id=transaction.id,
                invoice_id=invoice.id,
                match_method=match_method,
                confidence=_fallback_confidence(score, candidate=match_method == "AI_FALLBACK_CANDIDATE"),
                explanation=(
                    "AI 服务超时后由本地金额、日期和方向候选规则生成"
                    if match_method == "AI_FALLBACK_RULE"
                    else "AI 服务超时后由宽松候选规则生成，金额或主体可能不完全一致，需人工确认"
                ),
                confirmation_status="PENDING",
            )
        )
        existing_pairs.add((transaction.id, invoice.id))
        used_transaction_ids.add(transaction.id)
        used_invoice_ids.add(invoice.id)
        created_matches += 1
        if created_matches >= 20:
            break
    return created_matches


def _fallback_confidence(score: tuple[Decimal, int, int], *, candidate: bool = False) -> int:
    amount_gap, date_gap, party_penalty = score
    if candidate:
        amount_penalty = min(24, int(amount_gap / Decimal("1000")))
        date_penalty = min(10, date_gap // 4)
        return max(35, min(68, 68 - amount_penalty - date_penalty - party_penalty * 12))
    amount_penalty = min(int(amount_gap * Decimal("10")), 8)
    date_penalty = min(date_gap, 7)
    return max(70, 88 - amount_penalty - date_penalty - party_penalty * 10)


def _candidate_transactions(db: Session, package_id: UUID) -> list[BankTransaction]:
    used_transaction_ids, _used_invoice_ids = _used_entity_ids(db, package_id)
    line_transaction_ids = _accounting_line_transaction_ids(db, package_id)
    used_transaction_ids.update(line_transaction_ids)
    return [
        transaction
        for transaction in db.scalars(
            select(BankTransaction).where(BankTransaction.monthly_work_package_id == package_id).order_by(BankTransaction.transaction_date, BankTransaction.id)
        )
        if transaction.id not in used_transaction_ids
    ]


def _candidate_invoices(db: Session, package_id: UUID) -> list[Invoice]:
    _used_transaction_ids, used_invoice_ids = _used_entity_ids(db, package_id)
    return [
        invoice
        for invoice in db.scalars(
            select(Invoice)
            .where(Invoice.monthly_work_package_id == package_id)
            .order_by(Invoice.invoice_date, Invoice.invoice_number, Invoice.id)
        )
        if invoice.id not in used_invoice_ids
    ]


def _used_entity_ids(db: Session, package_id: UUID) -> tuple[set[UUID], set[UUID]]:
    transaction_ids: set[UUID] = set()
    invoice_ids: set[UUID] = set()
    for record in db.scalars(select(MatchRecord).where(MatchRecord.monthly_work_package_id == package_id)):
        if record.bank_transaction_id is not None:
            transaction_ids.add(record.bank_transaction_id)
        if record.invoice_id is not None:
            invoice_ids.add(record.invoice_id)
    return transaction_ids, invoice_ids


def _accounting_line_transaction_ids(db: Session, package_id: UUID) -> set[UUID]:
    ids: set[UUID] = set()
    rows = db.scalars(
        select(AccountingLine).where(
            AccountingLine.monthly_work_package_id == package_id,
            AccountingLine.source_type == "BANK_TRANSACTION",
        )
    )
    for line in rows:
        try:
            ids.add(UUID(line.source_id))
        except ValueError:
            continue
    return ids


def _existing_match_pairs(db: Session, package_id: UUID) -> set[tuple[UUID, UUID]]:
    pairs: set[tuple[UUID, UUID]] = set()
    for record in db.scalars(select(MatchRecord).where(MatchRecord.monthly_work_package_id == package_id)):
        if record.bank_transaction_id is not None and record.invoice_id is not None:
            pairs.add((record.bank_transaction_id, record.invoice_id))
    return pairs


def _build_ai_payload(
    *,
    transactions: list[BankTransaction],
    invoices: list[Invoice],
    enterprise_name: str,
) -> tuple[dict, dict[str, BankTransaction], dict[str, Invoice]]:
    transactions, invoices = _select_ai_candidates(transactions=transactions, invoices=invoices)
    party_aliases: dict[str, str] = {}

    def party_ref(name: str | None) -> str:
        if not name:
            return "-"
        if enterprise_name and name == enterprise_name:
            return "SELF"
        if name not in party_aliases:
            party_aliases[name] = f"P{len(party_aliases) + 1:03d}"
        return party_aliases[name]

    for transaction in transactions:
        party_ref(transaction.counterparty_name)
    for invoice in invoices:
        party_ref(invoice.seller_name)
        party_ref(invoice.buyer_name)

    names_to_mask = [enterprise_name, *party_aliases.keys()]

    def mask_text(text: str | None) -> str:
        value = text or ""
        for name in sorted((item for item in names_to_mask if item), key=len, reverse=True):
            replacement = "SELF" if name == enterprise_name else party_aliases.get(name, "PARTY")
            value = value.replace(name, replacement)
        return value

    transaction_by_ref: dict[str, BankTransaction] = {}
    invoice_by_ref: dict[str, Invoice] = {}
    bank_payload = []
    invoice_payload = []
    for index, transaction in enumerate(transactions, start=1):
        ref = f"T{index:03d}"
        transaction_by_ref[ref] = transaction
        bank_payload.append(
            {
                "ref": ref,
                "date": transaction.transaction_date.isoformat(),
                "direction": "OUT" if transaction.debit_amount and transaction.debit_amount != 0 else "IN",
                "amount": _format_decimal((transaction.debit_amount or Decimal("0")) or (transaction.credit_amount or Decimal("0"))),
                "summary": _truncate_text(mask_text(transaction.summary)),
                "counterparty_ref": party_ref(transaction.counterparty_name),
            }
        )
    for index, invoice in enumerate(invoices, start=1):
        ref = f"I{index:03d}"
        invoice_by_ref[ref] = invoice
        invoice_payload.append(
            {
                "ref": ref,
                "date": invoice.invoice_date.isoformat(),
                "direction": invoice.invoice_direction,
                "amount": _format_decimal(invoice.total_amount),
                "tax_amount": _format_decimal(invoice.tax_amount),
                "seller_ref": party_ref(invoice.seller_name),
                "buyer_ref": party_ref(invoice.buyer_name),
                "remark": _truncate_text(mask_text(_invoice_remark(invoice))),
            }
        )
    return {"bank_transactions": bank_payload, "invoices": invoice_payload}, transaction_by_ref, invoice_by_ref


def _select_ai_candidates(
    *,
    transactions: list[BankTransaction],
    invoices: list[Invoice],
) -> tuple[list[BankTransaction], list[Invoice]]:
    scored_transactions: list[tuple[tuple[Decimal, int, int], BankTransaction, list[Invoice]]] = []
    for transaction in transactions:
        scored_invoices = []
        for invoice in invoices:
            score = _candidate_score(transaction, invoice)
            if score is not None:
                scored_invoices.append((score, invoice))
        scored_invoices.sort(key=lambda item: item[0])
        if scored_invoices:
            scored_transactions.append((scored_invoices[0][0], transaction, [invoice for _score, invoice in scored_invoices[:3]]))

    if not scored_transactions:
        return transactions[:AI_PAYLOAD_MAX_TRANSACTIONS], invoices[:AI_PAYLOAD_MAX_INVOICES]

    scored_transactions.sort(key=lambda item: item[0])
    selected_transactions = [transaction for _score, transaction, _invoices in scored_transactions[:AI_PAYLOAD_MAX_TRANSACTIONS]]
    selected_invoices: list[Invoice] = []
    for _score, _transaction, candidate_invoices in scored_transactions[:AI_PAYLOAD_MAX_TRANSACTIONS]:
        for invoice in candidate_invoices:
            if not _contains_identity(selected_invoices, invoice):
                selected_invoices.append(invoice)
            if len(selected_invoices) >= AI_PAYLOAD_MAX_INVOICES:
                break
        if len(selected_invoices) >= AI_PAYLOAD_MAX_INVOICES:
            break
    return selected_transactions, selected_invoices


def _candidate_score(transaction: BankTransaction, invoice: Invoice, *, broad: bool = False) -> tuple[Decimal, int, int] | None:
    bank_direction = "OUT" if transaction.debit_amount and transaction.debit_amount != 0 else "IN"
    if bank_direction == "OUT" and invoice.invoice_direction != "INPUT":
        return None
    if bank_direction == "IN" and invoice.invoice_direction != "OUTPUT":
        return None

    transaction_amount = _transaction_amount(transaction)
    amount_gap = abs(Decimal(str(transaction_amount)) - Decimal(str(invoice.total_amount or Decimal("0"))))
    amount_base = max(abs(Decimal(str(transaction_amount))), abs(Decimal(str(invoice.total_amount or Decimal("0")))), Decimal("1.00"))
    allowed_gap = max(Decimal("1.00"), amount_base * (Decimal("0.60") if broad else Decimal("0.05")))
    if amount_gap > allowed_gap:
        return None

    date_gap = abs((transaction.transaction_date - invoice.invoice_date).days)
    if date_gap > (75 if broad else 45):
        return None

    counterparty = (transaction.counterparty_name or "").strip()
    invoice_counterparty_name = invoice.seller_name if invoice.invoice_direction == "INPUT" else invoice.buyer_name
    invoice_counterparty = (invoice_counterparty_name or "").strip()
    party_penalty = 0 if _party_names_may_match(counterparty, invoice_counterparty, broad=broad) else 1
    if broad and party_penalty and not counterparty and not invoice_counterparty:
        party_penalty = 2
    return amount_gap, date_gap, party_penalty


def _party_names_may_match(counterparty: str, invoice_counterparty: str, *, broad: bool) -> bool:
    if counterparty and invoice_counterparty and counterparty == invoice_counterparty:
        return True
    if not broad or not counterparty or not invoice_counterparty:
        return False
    compact_counterparty = _compact_party_name(counterparty)
    compact_invoice = _compact_party_name(invoice_counterparty)
    return bool(
        compact_counterparty
        and compact_invoice
        and (
            compact_counterparty in compact_invoice
            or compact_invoice in compact_counterparty
            or len(set(compact_counterparty) & set(compact_invoice)) >= min(4, len(compact_invoice))
        )
    )


def _compact_party_name(value: str) -> str:
    return (
        value.replace("有限公司", "")
        .replace("有限责任公司", "")
        .replace("昆山", "")
        .replace("苏州", "")
        .replace("上海", "")
        .replace(" ", "")
        .strip()
    )


def _transaction_amount(transaction: BankTransaction) -> Decimal:
    return (transaction.debit_amount or Decimal("0")) or (transaction.credit_amount or Decimal("0"))


def _contains_identity(items: list[Invoice], target: Invoice) -> bool:
    return any(item is target for item in items)


def _invoice_remark(invoice: Invoice) -> str:
    for key in ("备注", "remark", "摘要"):
        if invoice.raw_row_data and invoice.raw_row_data.get(key):
            return str(invoice.raw_row_data[key])
    return ""


def _truncate_text(value: str) -> str:
    if len(value) <= AI_TEXT_LIMIT:
        return value
    return f"{value[: AI_TEXT_LIMIT - 1]}…"


def _format_decimal(value: Decimal) -> str:
    return f"{Decimal(str(value)):.2f}"
