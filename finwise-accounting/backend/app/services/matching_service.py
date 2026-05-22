from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.org_context import get_current_organization_id
from app.models import AccountingLine, AuditLog, BankTransaction, Invoice, MatchRecord, MatchingRule, MonthlyWorkPackage
from app.rules.built_in import BUILT_IN_RULES


class MatchingDomainError(Exception):
    """Base exception for matching workflow domain errors."""


class MonthlyPackageNotFoundError(MatchingDomainError):
    pass


class MatchingValidationError(MatchingDomainError):
    pass


def amount_for_direction(transaction: BankTransaction, invoice: Invoice) -> Decimal:
    if invoice.invoice_direction == "OUTPUT":
        return transaction.credit_amount or Decimal("0")
    return transaction.debit_amount or Decimal("0")


def days_between(left: date, right: date) -> int:
    return abs((left - right).days)


def apply_built_in_rule(transaction: BankTransaction) -> dict | None:
    summary = transaction.summary or ""
    for rule in BUILT_IN_RULES:
        if any(keyword in summary for keyword in rule["keywords"]):
            return rule
    return None


def create_enterprise_matching_rule(
    db: Session,
    *,
    enterprise_id: UUID,
    summary_keywords: list[str],
    suggested_business_type: str,
    counterparty_pattern: str | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    invoice_direction: str | None = None,
) -> MatchingRule:
    organization_id = get_current_organization_id()
    invoice_direction = invoice_direction.upper() if invoice_direction else None
    rule = MatchingRule(
        organization_id=organization_id,
        enterprise_id=enterprise_id,
        scope="ENTERPRISE",
        summary_keywords=summary_keywords,
        counterparty_pattern=counterparty_pattern,
        min_amount=min_amount,
        max_amount=max_amount,
        invoice_direction=invoice_direction,
        suggested_business_type=suggested_business_type,
        source="USER_MEMORY",
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def apply_persisted_rule(db: Session, transaction: BankTransaction, package: MonthlyWorkPackage) -> dict | None:
    rule = find_matching_rule(db, transaction, package)
    if rule is None:
        return None
    direction = _direction_for_persisted_rule(rule, transaction)
    return {
        "business_type": rule.suggested_business_type,
        "line_label": rule.suggested_business_type,
        "direction": direction,
    }


def find_matching_rule(db: Session, transaction: BankTransaction, package: MonthlyWorkPackage) -> MatchingRule | None:
    rules = db.scalars(
        select(MatchingRule)
        .where(
            MatchingRule.organization_id == package.organization_id,
            MatchingRule.enterprise_id == package.enterprise_id,
        )
        .order_by(MatchingRule.created_at, MatchingRule.id)
    )
    for rule in rules:
        if _persisted_rule_matches(rule, transaction):
            return rule
    return None


def confirm_match(db: Session, *, match_id: UUID) -> dict:
    match = db.get(MatchRecord, match_id)
    if match is None:
        raise MatchingDomainError("Match record not found.")

    before = {"confirmation_status": match.confirmation_status}
    match.confirmation_status = "CONFIRMED"
    _add_audit_log(
        db,
        organization_id=match.organization_id,
        monthly_work_package_id=match.monthly_work_package_id,
        action="CONFIRM_MATCH",
        before_data=before,
        after_data={"confirmation_status": match.confirmation_status},
    )
    refresh_package_matching_summary(db, monthly_work_package_id=match.monthly_work_package_id, confirmed_when_zero=True)
    response = {"id": match.id, "confirmation_status": match.confirmation_status}
    db.commit()
    return response


def confirm_accounting_line(db: Session, *, line_id: UUID, save_as_rule: bool = False) -> dict:
    line = db.get(AccountingLine, line_id)
    if line is None:
        raise MatchingDomainError("Accounting line not found.")

    rule = _create_rule_from_accounting_line(db, line) if save_as_rule else None
    before = {"confirmation_status": line.confirmation_status}
    line.confirmation_status = "CONFIRMED"
    _add_audit_log(
        db,
        organization_id=line.organization_id,
        monthly_work_package_id=line.monthly_work_package_id,
        action="CONFIRM_ACCOUNTING_LINE",
        before_data=before,
        after_data={"confirmation_status": line.confirmation_status},
    )
    refresh_package_matching_summary(db, monthly_work_package_id=line.monthly_work_package_id, confirmed_when_zero=True)
    response = {"id": line.id, "confirmation_status": line.confirmation_status}
    if rule is not None:
        response["rule_id"] = rule.id
    db.commit()
    return response


def run_matching(db: Session, *, monthly_work_package_id: UUID) -> dict:
    package = _get_monthly_package(db, monthly_work_package_id)
    transactions = list(
        db.scalars(
            select(BankTransaction)
            .where(BankTransaction.monthly_work_package_id == monthly_work_package_id)
            .order_by(BankTransaction.transaction_date, BankTransaction.id)
        )
    )
    invoices = list(
        db.scalars(
            select(Invoice)
            .where(Invoice.monthly_work_package_id == monthly_work_package_id)
            .order_by(Invoice.invoice_date, Invoice.id)
        )
    )

    used_transaction_ids, used_invoice_ids, existing_pairs = _existing_match_state(db, monthly_work_package_id)
    exact_matches = 0

    for transaction in transactions:
        if transaction.id in used_transaction_ids:
            continue
        invoice = _find_exact_invoice(transaction, invoices, used_invoice_ids, existing_pairs)
        if invoice is None:
            continue

        db.add(
            MatchRecord(
                organization_id=package.organization_id,
                monthly_work_package_id=package.id,
                bank_transaction_id=transaction.id,
                invoice_id=invoice.id,
                match_method="AUTO_EXACT",
                confidence=95,
                explanation="金额一致且日期在7天内",
                confirmation_status="AUTO_CONFIRMED",
            )
        )
        used_transaction_ids.add(transaction.id)
        used_invoice_ids.add(invoice.id)
        existing_pairs.add((transaction.id, invoice.id))
        exact_matches += 1

    existing_line_keys, line_transaction_ids = _existing_accounting_line_state(db, monthly_work_package_id)
    used_transaction_ids.update(line_transaction_ids)
    rule_lines = 0
    for transaction in transactions:
        if transaction.id in used_transaction_ids:
            continue

        # Built-in rules run first so policy-maintained classifications take precedence over operator memory.
        rule = apply_built_in_rule(transaction)
        if rule is None:
            rule = apply_persisted_rule(db, transaction, package)
        if rule is None:
            continue

        line_key = ("BANK_TRANSACTION", str(transaction.id), rule["business_type"])
        if line_key in existing_line_keys:
            continue

        db.add(
            AccountingLine(
                organization_id=package.organization_id,
                monthly_work_package_id=package.id,
                source_type="BANK_TRANSACTION",
                source_id=str(transaction.id),
                business_type=rule["business_type"],
                direction=rule["direction"],
                amount=_transaction_amount(transaction),
                tax_amount=Decimal("0"),
                include_category=rule["direction"],
                confirmation_status="PENDING",
            )
        )
        existing_line_keys.add(line_key)
        used_transaction_ids.add(transaction.id)
        rule_lines += 1

    pending_confirmations = refresh_package_matching_summary(
        db,
        monthly_work_package_id=monthly_work_package_id,
    )
    db.commit()

    return {
        "exact_matches": exact_matches,
        "rule_lines": rule_lines,
        "pending_confirmations": pending_confirmations,
    }


def _get_monthly_package(db: Session, monthly_work_package_id: UUID) -> MonthlyWorkPackage:
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None or package.organization_id != get_current_organization_id():
        raise MonthlyPackageNotFoundError("Monthly work package not found.")
    return package


def _existing_match_state(db: Session, monthly_work_package_id: UUID) -> tuple[set[UUID], set[UUID], set[tuple[UUID, UUID]]]:
    used_transaction_ids: set[UUID] = set()
    used_invoice_ids: set[UUID] = set()
    existing_pairs: set[tuple[UUID, UUID]] = set()
    records = db.scalars(select(MatchRecord).where(MatchRecord.monthly_work_package_id == monthly_work_package_id))
    for record in records:
        if record.bank_transaction_id is not None:
            used_transaction_ids.add(record.bank_transaction_id)
        if record.invoice_id is not None:
            used_invoice_ids.add(record.invoice_id)
        if record.bank_transaction_id is not None and record.invoice_id is not None:
            existing_pairs.add((record.bank_transaction_id, record.invoice_id))
    return used_transaction_ids, used_invoice_ids, existing_pairs


def _find_exact_invoice(
    transaction: BankTransaction,
    invoices: list[Invoice],
    used_invoice_ids: set[UUID],
    existing_pairs: set[tuple[UUID, UUID]],
) -> Invoice | None:
    candidates = [
        invoice
        for invoice in invoices
        if invoice.id not in used_invoice_ids
        and (transaction.id, invoice.id) not in existing_pairs
        and amount_for_direction(transaction, invoice) == invoice.total_amount
        and days_between(transaction.transaction_date, invoice.invoice_date) <= 7
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda invoice: (days_between(transaction.transaction_date, invoice.invoice_date), invoice.id))


def _existing_accounting_line_state(db: Session, monthly_work_package_id: UUID) -> tuple[set[tuple[str, str, str]], set[UUID]]:
    lines = db.scalars(select(AccountingLine).where(AccountingLine.monthly_work_package_id == monthly_work_package_id))
    keys: set[tuple[str, str, str]] = set()
    transaction_ids: set[UUID] = set()
    for line in lines:
        keys.add((line.source_type, line.source_id, line.business_type))
        if line.source_type == "BANK_TRANSACTION":
            try:
                transaction_ids.add(UUID(line.source_id))
            except ValueError:
                continue
    return keys, transaction_ids


def _transaction_amount(transaction: BankTransaction) -> Decimal:
    if transaction.debit_amount and transaction.debit_amount != 0:
        return transaction.debit_amount
    return transaction.credit_amount or Decimal("0")


def refresh_package_matching_summary(
    db: Session,
    *,
    monthly_work_package_id: UUID,
    confirmed_when_zero: bool = False,
) -> int:
    package = _get_monthly_package(db, monthly_work_package_id)
    db.flush()
    transactions = list(db.scalars(select(BankTransaction).where(BankTransaction.monthly_work_package_id == package.id)))
    invoices = list(db.scalars(select(Invoice).where(Invoice.monthly_work_package_id == package.id)))
    used_transaction_ids, used_invoice_ids, _existing_pairs = _existing_match_state(db, package.id)
    _line_keys, line_transaction_ids = _existing_accounting_line_state(db, package.id)
    used_transaction_ids.update(line_transaction_ids)

    pending_line_count = db.query(AccountingLine).filter(
        AccountingLine.monthly_work_package_id == monthly_work_package_id,
        AccountingLine.confirmation_status == "PENDING",
    ).count()

    unmatched_transaction_count = sum(1 for transaction in transactions if transaction.id not in used_transaction_ids)
    unmatched_invoice_count = sum(1 for invoice in invoices if invoice.id not in used_invoice_ids)
    pending_confirmation_count = pending_line_count + unmatched_transaction_count + unmatched_invoice_count
    package.pending_confirmation_count = pending_confirmation_count
    if pending_confirmation_count == 0:
        package.matching_status = "CONFIRMED" if confirmed_when_zero else "COMPLETED"
    else:
        package.matching_status = "PENDING_CONFIRMATION"
    return pending_confirmation_count


def _persisted_rule_matches(rule: MatchingRule, transaction: BankTransaction) -> bool:
    summary = transaction.summary or ""
    keywords = rule.summary_keywords or []
    if keywords and not any(keyword in summary for keyword in keywords):
        return False

    if rule.counterparty_pattern:
        counterparty = transaction.counterparty_name or ""
        if rule.counterparty_pattern not in counterparty:
            return False

    amount = _transaction_amount(transaction)
    if rule.min_amount is not None and amount < rule.min_amount:
        return False
    if rule.max_amount is not None and amount > rule.max_amount:
        return False

    if rule.invoice_direction == "OUTPUT" and not (transaction.credit_amount and transaction.credit_amount != 0):
        return False
    if rule.invoice_direction == "INPUT" and not (transaction.debit_amount and transaction.debit_amount != 0):
        return False
    return True


def _direction_for_persisted_rule(rule: MatchingRule, transaction: BankTransaction) -> str:
    if rule.invoice_direction == "OUTPUT":
        return "INCOME"
    if rule.invoice_direction == "INPUT":
        return "EXPENSE"
    if transaction.debit_amount and transaction.debit_amount != 0:
        return "EXPENSE"
    return "INCOME"


def _create_rule_from_accounting_line(db: Session, line: AccountingLine) -> MatchingRule:
    if line.source_type != "BANK_TRANSACTION":
        raise MatchingValidationError("Only bank transaction accounting lines can be saved as rules.")

    try:
        transaction_id = UUID(line.source_id)
    except ValueError as exc:
        raise MatchingValidationError("Accounting line source is not a valid bank transaction.") from exc

    transaction = db.get(BankTransaction, transaction_id)
    if transaction is None or transaction.monthly_work_package_id != line.monthly_work_package_id:
        raise MatchingValidationError("Accounting line source bank transaction was not found.")

    package = _get_monthly_package(db, line.monthly_work_package_id)
    keyword = _extract_summary_keyword(transaction.summary)
    if not keyword:
        raise MatchingValidationError("Bank transaction summary is required to save a rule.")

    rule = MatchingRule(
        channel_id=line.channel_id,
        organization_id=package.organization_id,
        enterprise_id=package.enterprise_id,
        scope="ENTERPRISE",
        summary_keywords=[keyword],
        counterparty_pattern=transaction.counterparty_name,
        suggested_business_type=line.business_type,
        source="USER_CONFIRMED",
    )
    db.add(rule)
    db.flush()
    return rule


def _extract_summary_keyword(summary: str | None) -> str:
    normalized = (summary or "").strip()
    if not normalized:
        return ""
    if len(normalized) <= 6:
        return normalized

    for prefix in ("支付", "缴纳", "收到", "收取", "代扣", "银行", "转账"):
        if normalized.startswith(prefix) and len(normalized) > len(prefix):
            normalized = normalized[len(prefix) :]
            break

    for suffix in ("订阅费", "服务费", "手续费", "费用", "款项", "款", "费"):
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            normalized = normalized[: -len(suffix)]
            break

    if len(normalized) <= 6:
        return normalized
    return normalized[:4]


def _add_audit_log(
    db: Session,
    *,
    organization_id: UUID,
    monthly_work_package_id: UUID,
    action: str,
    before_data: dict,
    after_data: dict,
) -> None:
    db.add(
        AuditLog(
            organization_id=organization_id,
            monthly_work_package_id=monthly_work_package_id,
            actor="system",
            action=action,
            before_data=before_data,
            after_data=after_data,
        )
    )
