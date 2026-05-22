from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.org_context import get_current_organization_id
from app.models import AccountingLine, BankTransaction, Invoice, MatchRecord, MonthlyWorkPackage
from app.rules.built_in import BUILT_IN_RULES


class MatchingDomainError(Exception):
    """Base exception for matching workflow domain errors."""


class MonthlyPackageNotFoundError(MatchingDomainError):
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

    existing_line_keys = _existing_accounting_line_keys(db, monthly_work_package_id)
    rule_lines = 0
    for transaction in transactions:
        if transaction.id in used_transaction_ids:
            continue

        rule = apply_built_in_rule(transaction)
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
        rule_lines += 1

    pending_confirmations = _pending_confirmation_count(
        db,
        monthly_work_package_id=monthly_work_package_id,
        transactions=transactions,
        invoices=invoices,
        used_transaction_ids=used_transaction_ids,
        used_invoice_ids=used_invoice_ids,
    )
    package.pending_confirmation_count = pending_confirmations
    package.matching_status = "COMPLETED" if pending_confirmations == 0 else "PENDING_CONFIRMATION"
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


def _existing_accounting_line_keys(db: Session, monthly_work_package_id: UUID) -> set[tuple[str, str, str]]:
    lines = db.scalars(select(AccountingLine).where(AccountingLine.monthly_work_package_id == monthly_work_package_id))
    return {(line.source_type, line.source_id, line.business_type) for line in lines}


def _transaction_amount(transaction: BankTransaction) -> Decimal:
    if transaction.debit_amount and transaction.debit_amount != 0:
        return transaction.debit_amount
    return transaction.credit_amount or Decimal("0")


def _pending_confirmation_count(
    db: Session,
    *,
    monthly_work_package_id: UUID,
    transactions: list[BankTransaction],
    invoices: list[Invoice],
    used_transaction_ids: set[UUID],
    used_invoice_ids: set[UUID],
) -> int:
    db.flush()
    pending_line_count = db.query(AccountingLine).filter(
        AccountingLine.monthly_work_package_id == monthly_work_package_id,
        AccountingLine.confirmation_status == "PENDING",
    ).count()

    unmatched_transaction_count = sum(1 for transaction in transactions if transaction.id not in used_transaction_ids)
    unmatched_invoice_count = sum(1 for invoice in invoices if invoice.id not in used_invoice_ids)
    return pending_line_count + unmatched_transaction_count + unmatched_invoice_count
