from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from numbers import Real
from uuid import UUID

import pandas as pd
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.org_context import get_current_organization_id
from app.models import BankTransaction, Invoice, MonthlyWorkPackage


BANK_COLUMNS = {
    "transaction_date": ["交易日期", "日期", "交易时间"],
    "summary": ["摘要", "交易说明", "用途", "摘要说明"],
    "debit_amount": ["借方金额", "支出金额", "借记金额"],
    "credit_amount": ["贷方金额", "收入金额", "贷记金额"],
    "balance": ["余额", "账户余额", "当前余额"],
    "counterparty_name": ["对方户名", "对手方名称", "对方账户名"],
    "counterparty_account": ["对方账号", "对方账户", "对手方账号"],
}

INVOICE_COLUMNS = {
    "invoice_number": ["发票号码", "发票代码", "发票编码"],
    "invoice_date": ["开票日期", "日期"],
    "amount": ["金额", "不含税金额", "合计金额"],
    "tax_amount": ["税额", "税款"],
    "total_amount": ["价税合计", "总金额", "税后合计"],
    "seller_name": ["销售方名称", "销货方", "卖方名称"],
    "buyer_name": ["购买方名称", "购货方", "买方名称"],
}

SEPARATOR_DATE_RE = re.compile(
    r"^(?P<year>\d{4})(?P<separator>[-/.])(?P<month>\d{1,2})(?P=separator)(?P<day>\d{1,2})$"
)


class ImportDomainError(Exception):
    """Base exception for import workflow domain errors."""


class MonthlyPackageNotFoundError(ImportDomainError):
    pass


class ImportValidationError(ImportDomainError):
    pass


def pick(row: dict, aliases: list[str], default=None):
    for alias in aliases:
        value = row.get(alias)
        if not _is_blank(value):
            return value
    return default


def to_decimal(value) -> Decimal:
    if _is_blank(value):
        return Decimal("0")
    normalized = str(value).replace(",", "").replace("￥", "").replace("¥", "").strip()
    try:
        decimal_value = Decimal(normalized)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value}") from exc
    if not decimal_value.is_finite():
        raise ValueError(f"invalid decimal value: {value}")
    return decimal_value


def to_date(value) -> date:
    if _is_blank(value):
        raise ValueError("missing date value")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, Real) and not isinstance(value, bool):
        raise ValueError(f"numeric date values are not supported: {value}")
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError("missing date value")
        if normalized.isdigit():
            if len(normalized) != 8:
                raise ValueError(f"invalid date value: {value}")
            try:
                return datetime.strptime(normalized, "%Y%m%d").date()
            except ValueError as exc:
                raise ValueError(f"invalid date value: {value}") from exc
        matched = SEPARATOR_DATE_RE.fullmatch(normalized)
        if matched is None:
            raise ValueError(f"invalid date value: {value}")
        try:
            return date(
                int(matched.group("year")),
                int(matched.group("month")),
                int(matched.group("day")),
            )
        except ValueError as exc:
            raise ValueError(f"invalid date value: {value}") from exc
    raise ValueError(f"invalid date value: {value}")


def import_bank_rows(db: Session, *, monthly_work_package_id: UUID, rows: list[dict]) -> dict:
    _get_monthly_package(db, monthly_work_package_id)
    organization_id = get_current_organization_id()
    created = 0
    errors: list[dict] = []

    for index, row in enumerate(rows, start=1):
        try:
            debit_amount = to_decimal(pick(row, BANK_COLUMNS["debit_amount"], "0"))
            credit_amount = to_decimal(pick(row, BANK_COLUMNS["credit_amount"], "0"))
            if debit_amount == 0 and credit_amount == 0:
                raise ImportValidationError("missing debit or credit amount")

            transaction = BankTransaction(
                organization_id=organization_id,
                monthly_work_package_id=monthly_work_package_id,
                transaction_date=to_date(pick(row, BANK_COLUMNS["transaction_date"])),
                summary=str(pick(row, BANK_COLUMNS["summary"], "")),
                debit_amount=debit_amount,
                credit_amount=credit_amount,
                balance=to_decimal(pick(row, BANK_COLUMNS["balance"], "0")),
                counterparty_name=pick(row, BANK_COLUMNS["counterparty_name"]),
                counterparty_account=pick(row, BANK_COLUMNS["counterparty_account"]),
                raw_row_data=_json_safe_row(row),
            )
            db.add(transaction)
            created += 1
        except (ImportValidationError, TypeError, ValueError) as exc:
            errors.append({"row": index, "error": str(exc), "raw": _json_safe_row(row)})

    return _commit_import(db, created=created, errors=errors)


def import_invoice_rows(db: Session, *, monthly_work_package_id: UUID, direction: str, rows: list[dict]) -> dict:
    _get_monthly_package(db, monthly_work_package_id)
    invoice_direction = direction.upper()
    if invoice_direction not in {"INPUT", "OUTPUT"}:
        raise ImportValidationError("Invoice direction must be INPUT or OUTPUT.")

    organization_id = get_current_organization_id()
    created = 0
    errors: list[dict] = []

    for index, row in enumerate(rows, start=1):
        try:
            invoice = Invoice(
                organization_id=organization_id,
                monthly_work_package_id=monthly_work_package_id,
                invoice_direction=invoice_direction,
                invoice_number=_required_string(row, INVOICE_COLUMNS["invoice_number"], "invoice_number"),
                invoice_date=to_date(pick(row, INVOICE_COLUMNS["invoice_date"])),
                amount=_required_decimal(row, INVOICE_COLUMNS["amount"], "amount"),
                tax_amount=_required_decimal(row, INVOICE_COLUMNS["tax_amount"], "tax_amount"),
                total_amount=_required_decimal(row, INVOICE_COLUMNS["total_amount"], "total_amount"),
                seller_name=pick(row, INVOICE_COLUMNS["seller_name"]),
                buyer_name=pick(row, INVOICE_COLUMNS["buyer_name"]),
                raw_row_data=_json_safe_row(row),
            )
            db.add(invoice)
            created += 1
        except (TypeError, ValueError) as exc:
            errors.append({"row": index, "error": str(exc), "raw": _json_safe_row(row)})

    return _commit_import(db, created=created, errors=errors)


def _get_monthly_package(db: Session, monthly_work_package_id: UUID) -> MonthlyWorkPackage:
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None or package.organization_id != get_current_organization_id():
        raise MonthlyPackageNotFoundError("Monthly work package not found.")
    return package


def _is_blank(value) -> bool:
    if value in (None, ""):
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _required_decimal(row: dict, aliases: list[str], field_name: str) -> Decimal:
    value = pick(row, aliases)
    if _is_blank(value):
        raise ValueError(f"missing required decimal value: {field_name}")
    return to_decimal(value)


def _required_string(row: dict, aliases: list[str], field_name: str) -> str:
    value = pick(row, aliases)
    if _is_blank(value):
        raise ValueError(f"missing required text value: {field_name}")
    return str(value).strip()


def _commit_import(db: Session, *, created: int, errors: list[dict]) -> dict:
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        return {
            "created": 0,
            "errors": errors,
            "batch_errors": [{"error": str(exc)}],
        }
    return {"created": created, "errors": errors, "batch_errors": []}


def _json_safe_row(row: dict) -> dict:
    return {key: _json_safe_value(value) for key, value in row.items()}


def _json_safe_value(value):
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return value
