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
from app.models import BankTransaction, Enterprise, Invoice, MonthlyWorkPackage


BANK_COLUMNS = {
    "transaction_date": [
        "交易日期",
        "日期",
        "会计日期",
        "记账日期",
        "入账日期",
        "交易日",
        "交易日期[TransactionDate]",
        "交易时间",
    ],
    "summary": [
        "摘要",
        "交易说明",
        "用途",
        "摘要说明",
        "备注",
        "附言",
        "用途/附言",
        "用途附言",
        "业务摘要",
        "摘要[Reference]",
        "用途[Purpose]",
        "交易附言[Remark]",
    ],
    "debit_amount": [
        "借方金额",
        "支出金额",
        "借记金额",
        "借方发生额（支出）",
        "借方发生额/元(支取)",
        "借方发生额（支取）",
        "借方",
        "转出金额",
        "借方金额（出）",
        "借方发生额",
    ],
    "credit_amount": [
        "贷方金额",
        "收入金额",
        "贷记金额",
        "贷方发生额（收入）",
        "贷方发生额/元(收入)",
        "贷方",
        "转入金额",
        "贷方金额（进）",
        "贷方发生额",
    ],
    "single_amount": ["交易金额[TradeAmount]", "交易金额", "发生额", "金额"],
    "direction": ["收支标志", "借贷标志", "交易方向", "收付标志", "方向", "借贷", "交易类型[TransactionType]"],
    "balance": ["余额", "账户余额", "当前余额", "交易后余额[After-transactionbalance]"],
    "counterparty_name": [
        "对方户名",
        "对手方名称",
        "对方账户名",
        "对方单位",
        "收(付)方名称",
        "交易对手名称",
    ],
    "counterparty_account": ["对方账号", "对方账户", "对手方账号", "收(付)方账号"],
    "payer_name": ["付款人名称[Payer'sName]", "付款人名称", "付款方名称"],
    "payer_account": ["付款人账号[DebitAccountNo.]", "付款人账号", "付款方账号"],
    "payee_name": ["收款人名称[Payee'sName]", "收款人名称", "收款方名称"],
    "payee_account": ["收款人账号[Payee'sAccountNumber]", "收款人账号", "收款方账号"],
}

INVOICE_COLUMNS = {
    "invoice_number": ["发票号码", "数电发票号码", "发票代码", "发票编码"],
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
    normalized_aliases = [_normalize_key(alias) for alias in aliases]
    for key, value in row.items():
        if _is_blank(value):
            continue
        normalized_key = _normalize_key(key)
        if any(alias == normalized_key or alias in normalized_key for alias in normalized_aliases):
            return value
    return default


def to_decimal(value) -> Decimal:
    if _is_blank(value):
        return Decimal("0")
    normalized = str(value).replace(",", "").replace("￥", "").replace("¥", "").strip()
    if normalized.startswith("(") and normalized.endswith(")"):
        normalized = f"-{normalized[1:-1]}"
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
        numeric_text = str(int(value))
        if len(numeric_text) == 8:
            try:
                return datetime.strptime(numeric_text, "%Y%m%d").date()
            except ValueError as exc:
                raise ValueError(f"invalid date value: {value}") from exc
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
        if " " in normalized:
            date_part, _time_part = normalized.split(" ", 1)
            if date_part.isdigit() and len(date_part) == 8:
                try:
                    return datetime.strptime(date_part, "%Y%m%d").date()
                except ValueError as exc:
                    raise ValueError(f"invalid date value: {value}") from exc
        matched = SEPARATOR_DATE_RE.fullmatch(normalized)
        if matched is None and " " in normalized:
            date_part, _time_part = normalized.split(" ", 1)
            matched = SEPARATOR_DATE_RE.fullmatch(date_part)
            normalized = date_part
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
    package = _get_monthly_package(db, monthly_work_package_id)
    enterprise = db.get(Enterprise, package.enterprise_id)
    enterprise_name = enterprise.name if enterprise is not None else ""
    organization_id = get_current_organization_id()
    created = 0
    errors: list[dict] = []

    for index, row in enumerate(rows, start=1):
        if _is_bank_summary_row(row):
            continue
        try:
            debit_amount, credit_amount = _bank_amounts(row, enterprise_name=enterprise_name)
            if debit_amount == 0 and credit_amount == 0:
                raise ImportValidationError("missing debit or credit amount")

            transaction = BankTransaction(
                organization_id=organization_id,
                monthly_work_package_id=monthly_work_package_id,
                transaction_date=to_date(_normalize_accounting_date(row, pick(row, BANK_COLUMNS["transaction_date"]))),
                summary=str(pick(row, BANK_COLUMNS["summary"], "")),
                debit_amount=debit_amount,
                credit_amount=credit_amount,
                balance=to_decimal(pick(row, BANK_COLUMNS["balance"], "0")),
                counterparty_name=_counterparty_name(row, enterprise_name=enterprise_name),
                counterparty_account=_counterparty_account(row, enterprise_name=enterprise_name),
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


def _normalize_key(value) -> str:
    return str(value).strip().replace("\n", "").replace(" ", "")


def _is_bank_summary_row(row: dict) -> bool:
    values = [str(value).strip() for value in row.values() if not _is_blank(value)]
    joined = "|".join(values)
    if "交易笔数" in joined:
        return True
    if any(value in {"合计", "合计行", "本页合计", "总计"} for value in values):
        return True
    return False


def _bank_amounts(row: dict, *, enterprise_name: str) -> tuple[Decimal, Decimal]:
    debit_amount = to_decimal(pick(row, BANK_COLUMNS["debit_amount"], "0"))
    credit_amount = to_decimal(pick(row, BANK_COLUMNS["credit_amount"], "0"))
    if debit_amount != 0 or credit_amount != 0:
        return debit_amount, credit_amount

    single_amount = to_decimal(pick(row, BANK_COLUMNS["single_amount"], "0"))
    if single_amount == 0:
        return Decimal("0"), Decimal("0")

    direction = str(pick(row, BANK_COLUMNS["direction"], "")).strip()
    if _is_debit_direction(direction):
        return abs(single_amount), Decimal("0")
    if _is_credit_direction(direction):
        return Decimal("0"), abs(single_amount)

    payer_name = str(pick(row, BANK_COLUMNS["payer_name"], "")).strip()
    payee_name = str(pick(row, BANK_COLUMNS["payee_name"], "")).strip()
    if enterprise_name:
        if enterprise_name in payer_name:
            return abs(single_amount), Decimal("0")
        if enterprise_name in payee_name:
            return Decimal("0"), abs(single_amount)

    if single_amount < 0:
        return abs(single_amount), Decimal("0")
    raise ImportValidationError("missing debit or credit amount")


def _is_debit_direction(value: str) -> bool:
    return any(token in value for token in ("借", "支", "付", "出", "付款", "转出", "DEBIT", "PAY"))


def _is_credit_direction(value: str) -> bool:
    return any(token in value for token in ("贷", "收", "入", "进", "收款", "转入", "CREDIT", "RECEIVE"))


def _counterparty_name(row: dict, *, enterprise_name: str):
    payer_name = pick(row, BANK_COLUMNS["payer_name"])
    payee_name = pick(row, BANK_COLUMNS["payee_name"])
    if enterprise_name:
        if payer_name and enterprise_name in str(payer_name) and payee_name:
            return payee_name
        if payee_name and enterprise_name in str(payee_name) and payer_name:
            return payer_name
    return pick(row, BANK_COLUMNS["counterparty_name"])


def _counterparty_account(row: dict, *, enterprise_name: str):
    payer_name = pick(row, BANK_COLUMNS["payer_name"])
    payee_name = pick(row, BANK_COLUMNS["payee_name"])
    if enterprise_name:
        if payer_name and enterprise_name in str(payer_name):
            return pick(row, BANK_COLUMNS["payee_account"])
        if payee_name and enterprise_name in str(payee_name):
            return pick(row, BANK_COLUMNS["payer_account"])
    return pick(row, BANK_COLUMNS["counterparty_account"])


def _normalize_accounting_date(row: dict, value):
    if "会计日期" not in row or _is_blank(row.get("会计日期")):
        return value
    if isinstance(value, Real) and not isinstance(value, bool):
        numeric_text = str(int(value))
        if len(numeric_text) == 8:
            return numeric_text
    return value


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
