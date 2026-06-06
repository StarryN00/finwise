from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.org_context import get_current_organization_id
from app.models import Enterprise, HistoricalBalanceRow, HistoricalImportBatch, HistoricalLedgerEntry
from app.services.import_service import ImportValidationError, _json_safe_row, _required_string, to_date, to_decimal


class HistoricalImportError(Exception):
    pass


class HistoricalEnterpriseNotFoundError(HistoricalImportError):
    pass


@dataclass
class HistoricalImportResult:
    batch: HistoricalImportBatch
    ledger_errors: list[dict]
    balance_errors: list[dict]


LEDGER_AUXILIARY_COLUMNS = {
    "quantity": "数量",
    "foreign_currency": "外币",
    "customer_code": "客户编码",
    "customer_name": "客户",
    "supplier_code": "供应商编码",
    "supplier_name": "供应商",
    "inventory_code": "存货编码",
    "inventory_name": "存货",
    "project_code": "项目编码",
    "project_name": "项目",
    "department_code": "部门编码",
    "department_name": "部门",
    "person_code": "人员编码",
    "person_name": "人员",
}


def import_historical_books(
    db: Session,
    *,
    enterprise_id: UUID,
    fiscal_year: int,
    ledger_rows: list[dict],
    balance_rows: list[dict],
    ledger_filename: str,
    balance_filename: str,
    source_metadata: dict | None = None,
    file_hashes: dict | None = None,
) -> HistoricalImportBatch:
    enterprise = db.get(Enterprise, enterprise_id)
    organization_id = get_current_organization_id()
    if enterprise is None or enterprise.organization_id != organization_id:
        raise HistoricalEnterpriseNotFoundError("Enterprise not found.")
    source_metadata = source_metadata or {}
    _validate_source_metadata(source_metadata, enterprise_name=enterprise.name, fiscal_year=fiscal_year)

    existing_ledger_rows = _existing_count(db, HistoricalLedgerEntry, enterprise_id=enterprise_id, fiscal_year=fiscal_year)
    existing_balance_rows = _existing_count(db, HistoricalBalanceRow, enterprise_id=enterprise_id, fiscal_year=fiscal_year)
    batch = HistoricalImportBatch(
        organization_id=organization_id,
        enterprise_id=enterprise_id,
        fiscal_year=fiscal_year,
        ledger_filename=ledger_filename,
        balance_filename=balance_filename,
        source_metadata=source_metadata,
        file_hashes=file_hashes or {},
    )
    db.add(batch)
    db.flush()

    ledger_errors = _add_ledger_entries(
        db,
        batch=batch,
        organization_id=organization_id,
        enterprise_id=enterprise_id,
        fiscal_year=fiscal_year,
        rows=ledger_rows,
    )
    balance_errors = _add_balance_rows(
        db,
        batch=batch,
        organization_id=organization_id,
        enterprise_id=enterprise_id,
        fiscal_year=fiscal_year,
        rows=balance_rows,
    )
    db.flush()
    validation_summary = _validation_summary(db, batch.id, ledger_errors=ledger_errors, balance_errors=balance_errors)
    batch.created_ledger_rows = validation_summary["ledger_rows"]
    batch.created_balance_rows = validation_summary["balance_rows"]
    batch.validation_summary = validation_summary
    if ledger_errors or balance_errors:
        batch.status = "IMPORTED_WITH_ERRORS" if batch.created_ledger_rows or batch.created_balance_rows else "FAILED"
    if batch.created_ledger_rows or batch.created_balance_rows:
        batch.replaced_ledger_rows = existing_ledger_rows
        batch.replaced_balance_rows = existing_balance_rows
        _delete_previous_rows(db, enterprise_id=enterprise_id, fiscal_year=fiscal_year, current_batch_id=batch.id)
    db.flush()
    db.expunge(batch)

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HistoricalImportError(str(exc)) from exc
    return batch


def _add_ledger_entries(
    db: Session,
    *,
    batch: HistoricalImportBatch,
    organization_id: UUID,
    enterprise_id: UUID,
    fiscal_year: int,
    rows: list[dict],
) -> list[dict]:
    errors = []
    for index, row in enumerate(rows, start=1):
        try:
            voucher_date = to_date(row.get("date"))
            entry = HistoricalLedgerEntry(
                organization_id=organization_id,
                enterprise_id=enterprise_id,
                import_batch_id=batch.id,
                fiscal_year=fiscal_year,
                voucher_date=voucher_date,
                voucher_no=_required_string(row, ["voucher_no"], "voucher_no"),
                summary=str(row.get("summary") or ""),
                account_full_name=str(row.get("account_full_name") or ""),
                account_code=_required_string(row, ["account_code"], "account_code"),
                account_name=_required_string(row, ["account_name"], "account_name"),
                debit_amount=to_decimal(row.get("debit_amount")),
                credit_amount=to_decimal(row.get("credit_amount")),
                auxiliary=_ledger_auxiliary(row),
                raw_row_data=_json_safe_row(row),
            )
            db.add(entry)
        except (TypeError, ValueError, ImportValidationError) as exc:
            errors.append({"row": index, "error": str(exc), "raw": _json_safe_row(row)})
    return errors


def _add_balance_rows(
    db: Session,
    *,
    batch: HistoricalImportBatch,
    organization_id: UUID,
    enterprise_id: UUID,
    fiscal_year: int,
    rows: list[dict],
) -> list[dict]:
    errors = []
    for index, row in enumerate(rows, start=1):
        try:
            balance_row = HistoricalBalanceRow(
                organization_id=organization_id,
                enterprise_id=enterprise_id,
                import_batch_id=batch.id,
                fiscal_year=fiscal_year,
                account_code=_required_string(row, ["account_code"], "account_code"),
                account_name=_required_string(row, ["account_name"], "account_name"),
                opening_debit=to_decimal(row.get("opening_debit")),
                opening_credit=to_decimal(row.get("opening_credit")),
                period_debit=to_decimal(row.get("period_debit")),
                period_credit=to_decimal(row.get("period_credit")),
                closing_debit=to_decimal(row.get("closing_debit")),
                closing_credit=to_decimal(row.get("closing_credit")),
                raw_row_data=_json_safe_row(row),
            )
            db.add(balance_row)
        except (TypeError, ValueError, ImportValidationError) as exc:
            errors.append({"row": index, "error": str(exc), "raw": _json_safe_row(row)})
    return errors


def _validation_summary(db: Session, batch_id: UUID, *, ledger_errors: list[dict], balance_errors: list[dict]) -> dict:
    ledger_rows = _batch_count(db, HistoricalLedgerEntry, batch_id)
    balance_rows = _batch_count(db, HistoricalBalanceRow, batch_id)
    debit_total, credit_total = db.execute(
        select(
            func.coalesce(func.sum(HistoricalLedgerEntry.debit_amount), 0),
            func.coalesce(func.sum(HistoricalLedgerEntry.credit_amount), 0),
        ).where(HistoricalLedgerEntry.import_batch_id == batch_id)
    ).one()
    balance_period_debit, balance_period_credit = db.execute(
        select(
            func.coalesce(func.sum(HistoricalBalanceRow.period_debit), 0),
            func.coalesce(func.sum(HistoricalBalanceRow.period_credit), 0),
        ).where(HistoricalBalanceRow.import_batch_id == batch_id)
    ).one()
    voucher_rows = db.execute(
        select(
            HistoricalLedgerEntry.voucher_date,
            HistoricalLedgerEntry.voucher_no,
            func.sum(HistoricalLedgerEntry.debit_amount).label("debit_total"),
            func.sum(HistoricalLedgerEntry.credit_amount).label("credit_total"),
        )
        .where(HistoricalLedgerEntry.import_batch_id == batch_id)
        .group_by(HistoricalLedgerEntry.voucher_date, HistoricalLedgerEntry.voucher_no)
    ).all()
    all_unbalanced_vouchers = [
        {"voucher_date": item.voucher_date.isoformat(), "voucher_no": item.voucher_no}
        for item in voucher_rows
        if Decimal(item.debit_total or 0) != Decimal(item.credit_total or 0)
    ]
    return {
        "ledger_rows": ledger_rows,
        "balance_rows": balance_rows,
        "ledger_debit_total": str(Decimal(debit_total or 0)),
        "ledger_credit_total": str(Decimal(credit_total or 0)),
        "balance_period_debit_total": str(Decimal(balance_period_debit or 0)),
        "balance_period_credit_total": str(Decimal(balance_period_credit or 0)),
        "voucher_count": len(voucher_rows),
        "unbalanced_voucher_count": len(all_unbalanced_vouchers),
        "unbalanced_voucher_samples": all_unbalanced_vouchers[:10],
        "ledger_error_count": len(ledger_errors),
        "balance_error_count": len(balance_errors),
        "ledger_errors": ledger_errors[:20],
        "balance_errors": balance_errors[:20],
    }


def _ledger_auxiliary(row: dict) -> dict:
    auxiliary = {}
    for key, column in LEDGER_AUXILIARY_COLUMNS.items():
        for candidate in (key, column):
            if candidate in row and row[candidate] not in (None, ""):
                auxiliary[key] = row[candidate]
                break
    return auxiliary


def _validate_source_metadata(source_metadata: dict, *, enterprise_name: str, fiscal_year: int) -> None:
    company_names = [
        str(value).strip()
        for value in (
            source_metadata.get("ledger_company_name"),
            source_metadata.get("balance_company_name"),
        )
        if value
    ]
    for company_name in company_names:
        if company_name and enterprise_name not in company_name and company_name not in enterprise_name:
            raise HistoricalImportError("Uploaded historical files do not match the selected enterprise.")

    period_texts = [
        str(value)
        for value in (
            source_metadata.get("ledger_period_text"),
            source_metadata.get("balance_period_text"),
        )
        if value
    ]
    for period_text in period_texts:
        years = {int(match) for match in re.findall(r"(20\d{2})年", period_text)}
        if years and years != {fiscal_year}:
            raise HistoricalImportError("Uploaded historical files do not match the selected fiscal year.")


def _delete_previous_rows(db: Session, *, enterprise_id: UUID, fiscal_year: int, current_batch_id: UUID) -> None:
    organization_id = get_current_organization_id()
    common_filters = (
        lambda model: (
            model.organization_id == organization_id,
            model.enterprise_id == enterprise_id,
            model.fiscal_year == fiscal_year,
            model.import_batch_id != current_batch_id,
        )
    )
    db.execute(delete(HistoricalLedgerEntry).where(*common_filters(HistoricalLedgerEntry)))
    db.execute(delete(HistoricalBalanceRow).where(*common_filters(HistoricalBalanceRow)))


def _existing_count(db: Session, model, *, enterprise_id: UUID, fiscal_year: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(model)
            .where(
                model.organization_id == get_current_organization_id(),
                model.enterprise_id == enterprise_id,
                model.fiscal_year == fiscal_year,
            )
        )
        or 0
    )


def _batch_count(db: Session, model, batch_id: UUID) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(model.import_batch_id == batch_id)) or 0)
