from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.org_context import get_current_organization_id
from app.models import AccountingLine, BankTransaction, Invoice, MatchRecord, MonthlyStatement, MonthlyWorkPackage


class StatementDomainError(Exception):
    pass


class MonthlyPackageNotFoundError(StatementDomainError):
    pass


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def generate_monthly_statement(
    db: Session,
    *,
    monthly_work_package_id: UUID,
    formal_balance_sheet: dict | None = None,
    formal_income_statement: dict | None = None,
) -> MonthlyStatement:
    package = _get_monthly_package(db, monthly_work_package_id)
    totals = collect_confirmed_monthly_totals(db, monthly_work_package_id=package.id)

    estimated_income_statement = {
        "revenue": totals["output_amount"],
        "output_tax": totals["output_tax"],
        "cost": totals["input_amount"],
        "input_tax": totals["input_tax"],
        "expense": totals["expense"],
        "gross_profit": money(totals["output_amount"] - totals["input_amount"]),
        "operating_profit": money(totals["output_amount"] - totals["input_amount"] - totals["expense"]),
    }
    estimated_balance_sheet = {
        "bank_credit_total": totals["bank_credit_total"],
        "bank_debit_total": totals["bank_debit_total"],
        "cash_net_movement": totals["cash_net_movement"],
        "vat_payable_estimate": money(max(Decimal("0"), totals["output_tax"] - totals["input_tax"])),
    }

    statement = db.scalar(select(MonthlyStatement).where(MonthlyStatement.monthly_work_package_id == package.id))
    if statement is None:
        statement = MonthlyStatement(
            organization_id=package.organization_id,
            monthly_work_package_id=package.id,
        )
        db.add(statement)

    statement.estimated_balance_sheet = _json_money_dict(estimated_balance_sheet)
    statement.estimated_income_statement = _json_money_dict(estimated_income_statement)
    statement.formal_balance_sheet = formal_balance_sheet or statement.formal_balance_sheet or {}
    statement.formal_income_statement = formal_income_statement or statement.formal_income_statement or {}
    statement.difference_summary = _build_difference_summary(
        estimated_balance_sheet=estimated_balance_sheet,
        estimated_income_statement=estimated_income_statement,
        formal_balance_sheet=statement.formal_balance_sheet,
        formal_income_statement=statement.formal_income_statement,
    )
    db.commit()
    db.refresh(statement)
    return statement


def collect_confirmed_monthly_totals(db: Session, *, monthly_work_package_id: UUID) -> dict[str, Decimal]:
    invoice_ids = _confirmed_invoice_ids(db, monthly_work_package_id)
    output_amount = Decimal("0")
    output_tax = Decimal("0")
    input_amount = Decimal("0")
    input_tax = Decimal("0")

    if invoice_ids:
        invoices = db.scalars(
            select(Invoice).where(
                Invoice.monthly_work_package_id == monthly_work_package_id,
                Invoice.id.in_(invoice_ids),
                Invoice.status == "NORMAL",
            )
        )
        for invoice in invoices:
            if invoice.invoice_direction == "OUTPUT":
                output_amount += invoice.amount
                output_tax += invoice.tax_amount
            elif invoice.invoice_direction == "INPUT":
                input_amount += invoice.amount
                input_tax += invoice.tax_amount

    expense = Decimal("0")
    lines = db.scalars(
        select(AccountingLine).where(
            AccountingLine.monthly_work_package_id == monthly_work_package_id,
            AccountingLine.confirmation_status == "CONFIRMED",
            AccountingLine.direction == "EXPENSE",
        )
    )
    for line in lines:
        expense += line.amount

    bank_credit_total = Decimal("0")
    bank_debit_total = Decimal("0")
    transactions = db.scalars(select(BankTransaction).where(BankTransaction.monthly_work_package_id == monthly_work_package_id))
    for transaction in transactions:
        bank_credit_total += transaction.credit_amount or Decimal("0")
        bank_debit_total += transaction.debit_amount or Decimal("0")

    return {
        "output_amount": money(output_amount),
        "output_tax": money(output_tax),
        "input_amount": money(input_amount),
        "input_tax": money(input_tax),
        "expense": money(expense),
        "bank_credit_total": money(bank_credit_total),
        "bank_debit_total": money(bank_debit_total),
        "cash_net_movement": money(bank_credit_total - bank_debit_total),
    }


def count_unmatched_invoices(db: Session, *, monthly_work_package_id: UUID) -> int:
    confirmed_invoice_ids = _confirmed_invoice_ids(db, monthly_work_package_id)
    query = db.query(Invoice).filter(Invoice.monthly_work_package_id == monthly_work_package_id)
    if confirmed_invoice_ids:
        query = query.filter(Invoice.id.not_in(confirmed_invoice_ids))
    return query.count()


def _confirmed_invoice_ids(db: Session, monthly_work_package_id: UUID) -> set[UUID]:
    rows = db.scalars(
        select(MatchRecord.invoice_id).where(
            MatchRecord.monthly_work_package_id == monthly_work_package_id,
            MatchRecord.invoice_id.is_not(None),
            MatchRecord.confirmation_status.in_(("AUTO_CONFIRMED", "CONFIRMED")),
        )
    )
    return {invoice_id for invoice_id in rows if invoice_id is not None}


def _get_monthly_package(db: Session, monthly_work_package_id: UUID) -> MonthlyWorkPackage:
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None or package.organization_id != get_current_organization_id():
        raise MonthlyPackageNotFoundError("Monthly work package not found.")
    return package


def _build_difference_summary(
    *,
    estimated_balance_sheet: dict,
    estimated_income_statement: dict,
    formal_balance_sheet: dict,
    formal_income_statement: dict,
) -> dict:
    differences = {}
    for section, estimated, formal in (
        ("balance_sheet", estimated_balance_sheet, formal_balance_sheet),
        ("income_statement", estimated_income_statement, formal_income_statement),
    ):
        section_diff = {}
        for key, formal_value in formal.items():
            if key in estimated:
                section_diff[key] = _format_money(money(Decimal(str(estimated[key])) - Decimal(str(formal_value))))
        if section_diff:
            differences[section] = section_diff
    return differences


def _json_money_dict(data: dict) -> dict:
    return {key: _format_money(value) if isinstance(value, Decimal) else value for key, value in data.items()}


def _format_money(value: Decimal) -> str:
    return f"{value:.2f}"
