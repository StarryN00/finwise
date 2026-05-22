from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import UUID

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import TaxFilingDraft
from app.services.statement_service import (
    MonthlyPackageNotFoundError,
    collect_confirmed_monthly_totals,
    count_unmatched_invoices,
)


class TaxDraftNotFoundError(Exception):
    pass


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_vat_draft(*, output_amount: Decimal, output_tax: Decimal, input_amount: Decimal, input_tax: Decimal) -> dict:
    vat_payable = max(Decimal("0"), output_tax - input_tax)
    surcharge_estimate = money(vat_payable * Decimal("0.12"))
    return {
        "output_amount": money(output_amount),
        "output_tax": money(output_tax),
        "input_amount": money(input_amount),
        "input_tax": money(input_tax),
        "vat_payable": money(vat_payable),
        "surcharge_estimate": surcharge_estimate,
    }


def generate_tax_filing_draft(db: Session, *, monthly_work_package_id: UUID) -> TaxFilingDraft:
    totals = collect_confirmed_monthly_totals(db, monthly_work_package_id=monthly_work_package_id)
    draft_data = calculate_vat_draft(
        output_amount=totals["output_amount"],
        output_tax=totals["output_tax"],
        input_amount=totals["input_amount"],
        input_tax=totals["input_tax"],
    )
    unmatched_invoice_count = count_unmatched_invoices(db, monthly_work_package_id=monthly_work_package_id)
    draft_data = _json_money_dict(draft_data)
    draft_data["unmatched_invoice_count"] = unmatched_invoice_count
    draft_data["warnings"] = _warning_rows(unmatched_invoice_count)

    package = _package_from_totals_query(db, monthly_work_package_id)
    draft = db.scalar(select(TaxFilingDraft).where(TaxFilingDraft.monthly_work_package_id == monthly_work_package_id))
    if draft is None:
        draft = TaxFilingDraft(
            organization_id=package.organization_id,
            monthly_work_package_id=monthly_work_package_id,
        )
        db.add(draft)

    draft.data = draft_data
    draft.status = "DRAFT"
    db.commit()
    db.refresh(draft)
    return draft


def export_tax_filing_draft(db: Session, *, draft_id: UUID, output_dir: Path | None = None) -> Path:
    draft = db.get(TaxFilingDraft, draft_id)
    if draft is None:
        raise TaxDraftNotFoundError("Tax filing draft not found.")

    output_dir = output_dir or get_settings().upload_dir / "tax_exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    export_path = output_dir / f"tax-filing-{draft.monthly_work_package_id}.xlsx"

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "增值税申报草稿"
    sheet.append(["字段", "金额", "说明"])
    for row in _export_rows(draft.data):
        sheet.append(row)
    workbook.save(export_path)

    draft.export_path = str(export_path)
    draft.status = "EXPORTED"
    db.commit()
    db.refresh(draft)
    return export_path


def _package_from_totals_query(db: Session, monthly_work_package_id: UUID):
    from app.models import MonthlyWorkPackage

    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None:
        raise MonthlyPackageNotFoundError("Monthly work package not found.")
    return package


def _export_rows(data: dict) -> list[tuple[str, str, str]]:
    rows = [
        ("销项销售额", _format_money(data["output_amount"]), "本期销项不含税销售额"),
        ("销项税额", _format_money(data["output_tax"]), "本期销项税额"),
        ("进项金额", _format_money(data["input_amount"]), "本期进项不含税金额"),
        ("进项税额", _format_money(data["input_tax"]), "本期可抵扣进项税额"),
        ("本期应纳增值税", _format_money(data["vat_payable"]), "销项税额减进项税额"),
        ("附加税估算", _format_money(data["surcharge_estimate"]), "按12%估算"),
    ]
    rows.extend(("异常提醒", warning, "导出前请人工核对") for warning in data.get("warnings", []))
    return rows


def _warning_rows(unmatched_invoice_count: int) -> list[str]:
    if unmatched_invoice_count <= 0:
        return []
    return [f"未匹配发票{unmatched_invoice_count}张"]


def _format_money(value: Decimal | str | int | float) -> str:
    return f"{money(Decimal(str(value))):.2f}"


def _json_money_dict(data: dict) -> dict:
    return {key: _format_money(value) if isinstance(value, Decimal) else value for key, value in data.items()}
