from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccountingLine, BankTransaction, Enterprise, Invoice, MatchRecord, MonthlyWorkPackage, Report, TaxFilingDraft


def get_workspace_snapshot(db: Session) -> dict:
    enterprises = list(db.scalars(select(Enterprise).order_by(Enterprise.created_at.desc(), Enterprise.id)))
    packages = list(db.scalars(select(MonthlyWorkPackage).order_by(MonthlyWorkPackage.period_year.desc(), MonthlyWorkPackage.period_month.desc())))
    package_by_enterprise = {}
    for package in packages:
        package_by_enterprise.setdefault(package.enterprise_id, package)

    enterprise_rows = [_enterprise_row(db, enterprise, package_by_enterprise.get(enterprise.id)) for enterprise in enterprises]
    work_package_rows = [_package_row(db, package) for package in packages]
    latest_package = packages[0] if packages else None
    account_rows = _account_rows(db, latest_package) if latest_package else []
    checklist = _missing_checklist(db, latest_package) if latest_package else []

    return {
        "currentPeriod": _period(latest_package) if latest_package else "",
        "activeOrganization": "默认代账机构",
        "metrics": _metrics(enterprise_rows, work_package_rows),
        "enterprises": enterprise_rows,
        "workPackages": work_package_rows,
        "accountRows": account_rows,
        "missingChecklist": checklist,
    }


def _enterprise_row(db: Session, enterprise: Enterprise, package: MonthlyWorkPackage | None) -> dict:
    report_status = "DATA_INSUFFICIENT"
    if package is not None:
        report = db.scalar(select(Report).where(Report.monthly_work_package_id == package.id).order_by(Report.created_at.desc()))
        report_status = report.status if report is not None else "DATA_INSUFFICIENT"
    return {
        "id": str(enterprise.id),
        "name": enterprise.name,
        "taxpayerType": "一般纳税人" if enterprise.taxpayer_type == "GENERAL" else "小规模纳税人",
        "latestMonth": _period(package) if package else "-",
        "dataStatus": package.matching_status if package and package.matching_status != "NOT_STARTED" else (package.data_status if package else "PENDING_IMPORT"),
        "pendingConfirmations": package.pending_confirmation_count if package else 0,
        "reportStatus": report_status,
    }


def _package_row(db: Session, package: MonthlyWorkPackage) -> dict:
    enterprise = db.get(Enterprise, package.enterprise_id)
    tax_draft = db.scalar(select(TaxFilingDraft).where(TaxFilingDraft.monthly_work_package_id == package.id).order_by(TaxFilingDraft.created_at.desc()))
    report = db.scalar(select(Report).where(Report.monthly_work_package_id == package.id).order_by(Report.created_at.desc()))
    status = package.matching_status if package.matching_status not in {"NOT_STARTED", "COMPLETED"} else package.data_status
    if tax_draft is not None and package.pending_confirmation_count == 0:
        status = "READY_TO_EXPORT" if tax_draft.status == "DRAFT" else tax_draft.status
    return {
        "id": str(package.id),
        "enterpriseId": str(package.enterprise_id),
        "company": enterprise.name if enterprise else "未知企业",
        "period": _period(package),
        "status": status,
        "pending": package.pending_confirmation_count,
        "tax": _format_amount(tax_draft.data.get("vat_payable")) if tax_draft else "-",
        "taxDraftId": str(tax_draft.id) if tax_draft else "",
        "taxDraftStatus": tax_draft.status if tax_draft else "",
        "reportId": str(report.id) if report else "",
        "reportStatus": report.status if report else "DATA_INSUFFICIENT",
    }


def _account_rows(db: Session, package: MonthlyWorkPackage) -> list[dict]:
    rows = []
    matches = list(db.scalars(select(MatchRecord).where(MatchRecord.monthly_work_package_id == package.id)))
    match_by_transaction = {record.bank_transaction_id: record for record in matches if record.bank_transaction_id is not None}
    match_by_invoice = {record.invoice_id: record for record in matches if record.invoice_id is not None}
    lines = list(db.scalars(select(AccountingLine).where(AccountingLine.monthly_work_package_id == package.id)))
    line_by_transaction = {}
    for line in lines:
        if line.source_type == "BANK_TRANSACTION":
            line_by_transaction.setdefault(line.source_id, line)

    for transaction in db.scalars(select(BankTransaction).where(BankTransaction.monthly_work_package_id == package.id).order_by(BankTransaction.transaction_date, BankTransaction.id)):
        record = match_by_transaction.get(transaction.id)
        line = line_by_transaction.get(str(transaction.id))
        status = _record_status(record) if record else (line.confirmation_status if line else "PENDING_CONFIRMATION")
        business_type = record.match_method if record else (line.business_type if line else "待确认")
        rows.append(
            {
                "id": str(transaction.id),
                "packageId": str(package.id),
                "type": "流水",
                "date": transaction.transaction_date.isoformat(),
                "summary": transaction.summary,
                "status": status,
                "confidence": record.confidence if record else (90 if line else 0),
                "businessType": business_type,
                "amount": _format_amount((transaction.credit_amount or Decimal("0")) or (transaction.debit_amount or Decimal("0"))),
                "tax": "-",
                "confirmType": _confirm_type(record, line, fallback="unmatched"),
                "confirmId": _confirm_id(record, line),
                "sourceType": "BANK_TRANSACTION",
                "sourceId": str(transaction.id),
            }
        )

    for invoice in db.scalars(select(Invoice).where(Invoice.monthly_work_package_id == package.id).order_by(Invoice.invoice_date, Invoice.id)):
        record = match_by_invoice.get(invoice.id)
        rows.append(
            {
                "id": str(invoice.id),
                "packageId": str(package.id),
                "type": "发票",
                "date": invoice.invoice_date.isoformat(),
                "summary": f"{invoice.invoice_direction} {invoice.invoice_number}",
                "status": _record_status(record),
                "confidence": record.confidence if record else 0,
                "businessType": "销项发票" if invoice.invoice_direction == "OUTPUT" else "进项发票",
                "amount": _format_amount(invoice.total_amount),
                "tax": _format_amount(invoice.tax_amount),
                "confirmType": "match" if record else "unmatched",
                "confirmId": str(record.id) if record else "",
                "sourceType": "INVOICE",
                "sourceId": str(invoice.id),
            }
        )

    for line in sorted(lines, key=lambda item: (item.created_at, item.id)):
        rows.append(
            {
                "id": str(line.id),
                "packageId": str(package.id),
                "type": "账目",
                "date": "-",
                "summary": line.business_type,
                "status": line.confirmation_status,
                "confidence": 0,
                "businessType": line.business_type,
                "amount": _format_amount(line.amount),
                "tax": _format_amount(line.tax_amount),
                "confirmType": "accountingLine",
                "confirmId": str(line.id),
                "sourceType": line.source_type,
                "sourceId": line.source_id,
            }
        )
    return rows


def _missing_checklist(db: Session, package: MonthlyWorkPackage | None) -> list[dict]:
    if package is None:
        return []
    bank_count = db.query(BankTransaction).filter(BankTransaction.monthly_work_package_id == package.id).count()
    output_count = db.query(Invoice).filter(Invoice.monthly_work_package_id == package.id, Invoice.invoice_direction == "OUTPUT").count()
    input_count = db.query(Invoice).filter(Invoice.monthly_work_package_id == package.id, Invoice.invoice_direction == "INPUT").count()
    report_count = db.query(Report).filter(Report.monthly_work_package_id == package.id).count()
    return [
        {"label": "银行流水", "done": bank_count > 0},
        {"label": "销项明细", "done": output_count > 0},
        {"label": "进项明细", "done": input_count > 0},
        {"label": "人工确认", "done": package.pending_confirmation_count == 0},
        {"label": "健康报告数据", "done": report_count > 0},
    ]


def _metrics(enterprises: list[dict], packages: list[dict]) -> list[dict]:
    pending_count = sum(1 for package in packages if package["pending"] > 0)
    confirmed_count = sum(1 for package in packages if package["pending"] == 0 and package["status"] in {"CONFIRMED", "READY_TO_EXPORT", "EXPORTED"})
    export_count = sum(1 for package in packages if package["status"] in {"READY_TO_EXPORT", "EXPORTED"})
    return [
        {"label": "企业数量", "value": str(len(enterprises)), "subtext": "当前数据库客户数", "tone": "primary"},
        {"label": "待处理工作包", "value": str(pending_count), "subtext": "仍有待确认事项", "tone": "warning"},
        {"label": "可导出申报", "value": str(export_count), "subtext": "已生成申报草稿", "tone": "success"},
    ]


def _record_status(record: MatchRecord | None) -> str:
    if record is None:
        return "PENDING_CONFIRMATION"
    return "CONFIRMED" if record.confirmation_status in {"AUTO_CONFIRMED", "CONFIRMED"} else record.confirmation_status


def _confirm_type(record: MatchRecord | None, line: AccountingLine | None, *, fallback: str) -> str:
    if record is not None:
        return "match"
    if line is not None:
        return "accountingLine"
    return fallback


def _confirm_id(record: MatchRecord | None, line: AccountingLine | None) -> str:
    if record is not None:
        return str(record.id)
    if line is not None:
        return str(line.id)
    return ""


def _period(package: MonthlyWorkPackage | None) -> str:
    if package is None:
        return ""
    return f"{package.period_year}-{package.period_month:02d}"


def _format_amount(value) -> str:
    if value in (None, ""):
        return "-"
    return f"{Decimal(str(value)):,.2f}"
