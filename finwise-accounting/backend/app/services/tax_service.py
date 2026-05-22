from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from html import escape
from pathlib import Path
from uuid import UUID

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.org_context import get_current_organization_id
from app.models import Enterprise, Invoice, MonthlyWorkPackage, TaxFilingDraft
from app.services.statement_service import (
    MonthlyPackageNotFoundError,
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


def collect_invoice_tax_totals(db: Session, *, monthly_work_package_id: UUID) -> dict[str, Decimal]:
    package = _get_monthly_package(db, monthly_work_package_id)
    totals = {
        "output_amount": Decimal("0"),
        "output_tax": Decimal("0"),
        "input_amount": Decimal("0"),
        "input_tax": Decimal("0"),
    }
    invoices = db.scalars(
        select(Invoice).where(
            Invoice.monthly_work_package_id == package.id,
            Invoice.status == "NORMAL",
        )
    )
    for invoice in invoices:
        if invoice.invoice_direction == "OUTPUT":
            totals["output_amount"] += invoice.amount
            totals["output_tax"] += invoice.tax_amount
        elif invoice.invoice_direction == "INPUT":
            totals["input_amount"] += invoice.amount
            totals["input_tax"] += invoice.tax_amount

    return {key: money(value) for key, value in totals.items()}


def generate_tax_filing_draft(db: Session, *, monthly_work_package_id: UUID) -> TaxFilingDraft:
    totals = collect_invoice_tax_totals(db, monthly_work_package_id=monthly_work_package_id)
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

    package = _get_monthly_package(db, monthly_work_package_id)
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


def get_tax_filing_draft(db: Session, *, draft_id: UUID) -> TaxFilingDraft:
    draft = db.get(TaxFilingDraft, draft_id)
    if draft is None or draft.organization_id != get_current_organization_id():
        raise TaxDraftNotFoundError("Tax filing draft not found.")
    return draft


def update_tax_filing_draft(
    db: Session,
    *,
    draft_id: UUID,
    output_amount: Decimal,
    output_tax: Decimal,
    input_amount: Decimal,
    input_tax: Decimal,
) -> TaxFilingDraft:
    draft = get_tax_filing_draft(db, draft_id=draft_id)
    recalculated = calculate_vat_draft(
        output_amount=output_amount,
        output_tax=output_tax,
        input_amount=input_amount,
        input_tax=input_tax,
    )
    draft_data = _json_money_dict(recalculated)
    draft_data["unmatched_invoice_count"] = draft.data.get("unmatched_invoice_count", 0)
    draft_data["warnings"] = draft.data.get("warnings", [])
    draft.data = draft_data
    draft.status = "DRAFT"
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = expire_on_commit
    return draft


def export_tax_filing_draft(db: Session, *, draft_id: UUID, output_dir: Path | None = None) -> Path:
    draft = get_tax_filing_draft(db, draft_id=draft_id)

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


def render_tax_filing_draft_html(db: Session, *, draft_id: UUID) -> str:
    draft = get_tax_filing_draft(db, draft_id=draft_id)
    package = db.get(MonthlyWorkPackage, draft.monthly_work_package_id)
    enterprise = db.get(Enterprise, package.enterprise_id) if package else None
    enterprise_name = enterprise.name if enterprise else "未知企业"
    period = f"{package.period_year}-{package.period_month:02d}" if package else "-"
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{escape(enterprise_name)} {period} 增值税申报草稿</title>
  <style>
    body {{ margin: 0; padding: 32px; color: #172033; background: #f5f7fb; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ max-width: 960px; margin: 0 auto; }}
    header, section {{ margin-bottom: 18px; padding: 22px; border: 1px solid #dbe3ef; border-radius: 8px; background: #fff; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    p {{ margin: 0; color: #667085; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #edf1f7; text-align: left; }}
    th {{ color: #667085; font-weight: 600; background: #f8fafc; }}
    td:nth-child(2) {{ text-align: right; font-variant-numeric: tabular-nums; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{escape(enterprise_name)} {period} 增值税申报草稿</h1>
      <p>基于本期已导入的电子税务局进项、销项明细生成；未匹配发票保留为核对提醒。</p>
    </header>
    <section>
      {_render_tax_rows_table(draft.data)}
    </section>
  </main>
</body>
</html>
"""


def _get_monthly_package(db: Session, monthly_work_package_id: UUID) -> MonthlyWorkPackage:
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None or package.organization_id != get_current_organization_id():
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


def _render_tax_rows_table(data: dict) -> str:
    rows = "\n".join(
        f"<tr><td>{escape(label)}</td><td>{escape(amount)}</td><td>{escape(note)}</td></tr>"
        for label, amount, note in _export_rows(data)
    )
    return f"<table><thead><tr><th>申报项目</th><th>金额</th><th>说明</th></tr></thead><tbody>{rows}</tbody></table>"
