from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AccountingLine,
    BankTransaction,
    Enterprise,
    Invoice,
    MatchRecord,
    MonthlyStatement,
    MonthlyWorkPackage,
    Report,
    TaxFilingDraft,
    TechnologyProfile,
    TechnologyTag,
)


BUSINESS_TYPE_LABELS = {
    "AUTO_EXACT": "自动匹配",
    "AI_SUGGESTED": "AI 建议匹配",
    "AI_FALLBACK_RULE": "需要规则匹配",
    "AI_FALLBACK_CANDIDATE": "疑似匹配候选",
    "MANUAL_CANDIDATE": "人工候选",
    "MANUAL_INVOICE_ONLY": "手工确认发票",
    "RULE": "规则匹配",
    "BANK_FEE": "银行手续费",
    "CONSULTING_SERVICE": "咨询服务",
    "OTHER_EXPENSE": "其他支出",
    "OTHER_INCOME": "其他收入",
    "OUTPUT_REVENUE": "销售收入",
    "INVOICE_CONFIRMED": "发票确认",
}


def get_workspace_snapshot(db: Session, selected_package_id: UUID | None = None) -> dict:
    enterprises = list(db.scalars(select(Enterprise).order_by(Enterprise.created_at.desc(), Enterprise.id)))
    packages = list(db.scalars(select(MonthlyWorkPackage).order_by(MonthlyWorkPackage.period_year.desc(), MonthlyWorkPackage.period_month.desc())))
    package_by_enterprise = {}
    for package in packages:
        package_by_enterprise.setdefault(package.enterprise_id, package)

    enterprise_rows = [_enterprise_row(db, enterprise, package_by_enterprise.get(enterprise.id)) for enterprise in enterprises]
    work_package_rows = [_package_row(db, package) for package in packages]
    selected_package = _selected_package(packages, selected_package_id)
    account_rows = _account_rows(db, selected_package) if selected_package else []
    checklist = _missing_checklist(db, selected_package) if selected_package else []

    return {
        "currentPeriod": _period(selected_package) if selected_package else "",
        "activeOrganization": "默认代账机构",
        "selectedPackageId": str(selected_package.id) if selected_package else "",
        "metrics": _metrics(enterprise_rows, work_package_rows),
        "enterprises": enterprise_rows,
        "workPackages": work_package_rows,
        "accountRows": account_rows,
        "missingChecklist": checklist,
    }


def _selected_package(packages: list[MonthlyWorkPackage], selected_package_id: UUID | None) -> MonthlyWorkPackage | None:
    if not packages:
        return None
    if selected_package_id is None:
        return packages[0]
    return next((package for package in packages if package.id == selected_package_id), packages[0])


def _enterprise_row(db: Session, enterprise: Enterprise, package: MonthlyWorkPackage | None) -> dict:
    report_status = "DATA_INSUFFICIENT"
    if package is not None:
        report = db.scalar(select(Report).where(Report.monthly_work_package_id == package.id).order_by(Report.created_at.desc()))
        report_status = report.status if report is not None else "DATA_INSUFFICIENT"
    technology_profile = db.scalar(
        select(TechnologyProfile).where(TechnologyProfile.enterprise_id == enterprise.id).order_by(TechnologyProfile.updated_at.desc())
    )
    technology_summary = _technology_profile_summary(db, technology_profile)
    return {
        "id": str(enterprise.id),
        "name": enterprise.name,
        "unifiedSocialCreditCode": enterprise.unified_social_credit_code,
        "taxpayerType": "一般纳税人" if enterprise.taxpayer_type == "GENERAL" else "小规模纳税人",
        "taxpayerTypeCode": enterprise.taxpayer_type,
        "industry": enterprise.industry,
        "province": enterprise.province,
        "city": enterprise.city,
        "status": enterprise.status,
        "latestMonth": _period(package) if package else "-",
        "dataStatus": package.matching_status if package and package.matching_status != "NOT_STARTED" else (package.data_status if package else "PENDING_IMPORT"),
        "pendingConfirmations": package.pending_confirmation_count if package else 0,
        "reportStatus": report_status,
        "technologyProfileStatus": technology_profile.overall_status if technology_profile else "NOT_SCANNED",
        "technologyProfileSummary": technology_profile.summary if technology_profile else "",
        "technologyTags": technology_summary["technologyTags"],
        "ipSummary": technology_summary["ipSummary"],
        "lastTechnologyScanAt": technology_profile.last_scanned_at.isoformat() if technology_profile and technology_profile.last_scanned_at else "",
    }


def _technology_profile_summary(db: Session, profile: TechnologyProfile | None) -> dict:
    if profile is None:
        return {"technologyTags": [], "ipSummary": "-"}
    tags = list(
        db.scalars(
            select(TechnologyTag)
            .where(TechnologyTag.profile_id == profile.id, TechnologyTag.status == "HIT")
            .order_by(TechnologyTag.category, TechnologyTag.name)
        )
    )
    technology_tags = [tag.name for tag in tags if tag.category in {"TECH_QUALIFICATION", "QCC_TECH_CERTIFICATION"}]
    ip_parts = [
        f"{tag.name} {tag.value}" if tag.value else tag.name
        for tag in tags
        if tag.category in {"INTELLECTUAL_PROPERTY", "QCC_INTELLECTUAL_PROPERTY"}
    ]
    return {
        "technologyTags": technology_tags,
        "ipSummary": " / ".join(ip_parts) if ip_parts else "-",
    }


def _package_row(db: Session, package: MonthlyWorkPackage) -> dict:
    enterprise = db.get(Enterprise, package.enterprise_id)
    statement = db.scalar(select(MonthlyStatement).where(MonthlyStatement.monthly_work_package_id == package.id).order_by(MonthlyStatement.created_at.desc()))
    tax_draft = db.scalar(select(TaxFilingDraft).where(TaxFilingDraft.monthly_work_package_id == package.id).order_by(TaxFilingDraft.created_at.desc()))
    report = db.scalar(select(Report).where(Report.monthly_work_package_id == package.id).order_by(Report.created_at.desc()))
    status = package.matching_status if package.matching_status not in {"NOT_STARTED", "COMPLETED"} else package.data_status
    matching_ready = package.matching_status in {"CONFIRMED", "COMPLETED"}
    if tax_draft is not None and package.pending_confirmation_count == 0 and matching_ready:
        status = "READY_TO_EXPORT" if tax_draft.status == "DRAFT" else tax_draft.status
    return {
        "id": str(package.id),
        "enterpriseId": str(package.enterprise_id),
        "company": enterprise.name if enterprise else "未知企业",
        "period": _period(package),
        "status": status,
        "pending": package.pending_confirmation_count,
        "statementId": str(statement.id) if statement else "",
        "tax": _format_amount(tax_draft.data.get("vat_payable")) if tax_draft else "-",
        "taxDraftId": str(tax_draft.id) if tax_draft else "",
        "taxDraftStatus": tax_draft.status if tax_draft else "",
        "reportId": str(report.id) if report else "",
        "reportStatus": report.status if report else "DATA_INSUFFICIENT",
    }


def _account_rows(db: Session, package: MonthlyWorkPackage) -> list[dict]:
    rows = []
    matches = list(db.scalars(select(MatchRecord).where(MatchRecord.monthly_work_package_id == package.id)))
    enterprise = db.get(Enterprise, package.enterprise_id)
    enterprise_name = enterprise.name if enterprise else "本企业"
    transactions = list(
        db.scalars(
            select(BankTransaction)
            .where(BankTransaction.monthly_work_package_id == package.id)
            .order_by(BankTransaction.transaction_date, BankTransaction.id)
        )
    )
    invoices = list(
        db.scalars(
            select(Invoice).where(Invoice.monthly_work_package_id == package.id).order_by(Invoice.invoice_date, Invoice.id)
        )
    )
    transaction_by_id = {transaction.id: transaction for transaction in transactions}
    invoice_by_id = {invoice.id: invoice for invoice in invoices}
    match_by_transaction = {record.bank_transaction_id: record for record in matches if record.bank_transaction_id is not None}
    match_by_invoice = {record.invoice_id: record for record in matches if record.invoice_id is not None}
    lines = list(db.scalars(select(AccountingLine).where(AccountingLine.monthly_work_package_id == package.id)))
    line_by_transaction = {}
    for line in lines:
        if line.source_type == "BANK_TRANSACTION":
            line_by_transaction.setdefault(line.source_id, line)

    emitted_transaction_ids = set()
    emitted_invoice_ids = set()
    emitted_line_ids = set()

    for record in sorted(matches, key=lambda item: (item.created_at, item.id)):
        transaction = transaction_by_id.get(record.bank_transaction_id) if record.bank_transaction_id else None
        invoice = invoice_by_id.get(record.invoice_id) if record.invoice_id else None
        if transaction is not None and invoice is not None:
            rows.append(_merged_source_row(record, transaction, invoice, enterprise_name=enterprise_name))
            emitted_transaction_ids.add(transaction.id)
            emitted_invoice_ids.add(invoice.id)
        elif invoice is not None:
            rows.append(_invoice_only_row(record, invoice, enterprise_name=enterprise_name))
            emitted_invoice_ids.add(invoice.id)

    for transaction in transactions:
        if transaction.id in emitted_transaction_ids:
            continue
        record = match_by_transaction.get(transaction.id)
        line = line_by_transaction.get(str(transaction.id))
        if line is not None:
            emitted_line_ids.add(line.id)
        status = _record_status(record) if record else (line.confirmation_status if line else "PENDING_CONFIRMATION")
        business_type = _business_type_label(record.match_method if record else (line.business_type if line else "待确认"))
        rows.append(
            {
                "id": str(transaction.id),
                "packageId": str(package.id),
                "type": "流水",
                "date": transaction.transaction_date.isoformat(),
                "summary": transaction.summary,
                "remark": transaction.summary or "-",
                "status": status,
                "confidence": record.confidence if record else (90 if line else 0),
                "businessType": business_type,
                "amount": _format_amount((transaction.credit_amount or Decimal("0")) or (transaction.debit_amount or Decimal("0"))),
                "tax": "-",
                "directionType": _bank_direction_type(transaction),
                "transactionCounterparty": transaction.counterparty_name or "-",
                "invoiceCounterparty": "-",
                "payer": _bank_payer(transaction, enterprise_name),
                "payee": _bank_payee(transaction, enterprise_name),
                "seller": "-",
                "buyer": "-",
                "invoiceNumber": "-",
                "sourceCompleteness": "缺失发票主体",
                "confirmType": _confirm_type(record, line, fallback="unmatched"),
                "confirmId": _confirm_id(record, line),
                "sourceType": "BANK_TRANSACTION",
                "sourceId": str(transaction.id),
            }
        )

    for invoice in invoices:
        if invoice.id in emitted_invoice_ids:
            continue
        record = match_by_invoice.get(invoice.id)
        rows.append(
            {
                "id": str(invoice.id),
                "packageId": str(package.id),
                "type": "发票",
                "date": invoice.invoice_date.isoformat(),
                "summary": f"{invoice.invoice_direction} {invoice.invoice_number}",
                "remark": _invoice_remark(invoice),
                "status": _record_status(record),
                "confidence": record.confidence if record else 0,
                "businessType": "销项发票" if invoice.invoice_direction == "OUTPUT" else "进项发票",
                "amount": _format_amount(invoice.total_amount),
                "tax": _format_amount(invoice.tax_amount),
                "directionType": _invoice_direction_type(invoice),
                "transactionCounterparty": "-",
                "invoiceCounterparty": _invoice_counterparty(invoice, enterprise_name),
                "payer": "-",
                "payee": "-",
                "seller": invoice.seller_name or "-",
                "buyer": invoice.buyer_name or "-",
                "invoiceNumber": invoice.invoice_number,
                "sourceCompleteness": "缺失转账主体",
                "confirmType": "match" if record else "unmatched",
                "confirmId": str(record.id) if record else "",
                "sourceType": "INVOICE",
                "sourceId": str(invoice.id),
            }
        )

    for line in sorted(lines, key=lambda item: (item.created_at, item.id)):
        if line.id in emitted_line_ids:
            continue
        rows.append(
            {
                "id": str(line.id),
                "packageId": str(package.id),
                "type": "账目",
                "date": "-",
                "summary": line.business_type,
                "remark": line.business_type,
                "status": line.confirmation_status,
                "confidence": 0,
                "businessType": _business_type_label(line.business_type),
                "amount": _format_amount(line.amount),
                "tax": _format_amount(line.tax_amount),
                "directionType": "人工",
                "transactionCounterparty": "-",
                "invoiceCounterparty": "-",
                "payer": "-",
                "payee": "-",
                "seller": "-",
                "buyer": "-",
                "invoiceNumber": "-",
                "sourceCompleteness": "人工账目",
                "confirmType": "accountingLine",
                "confirmId": str(line.id),
                "sourceType": line.source_type,
                "sourceId": line.source_id,
            }
        )
    return rows


def _merged_source_row(
    record: MatchRecord,
    transaction: BankTransaction,
    invoice: Invoice,
    *,
    enterprise_name: str,
) -> dict:
    return {
        "id": str(record.id),
        "packageId": str(record.monthly_work_package_id),
        "type": "流水+发票",
        "date": min(transaction.transaction_date, invoice.invoice_date).isoformat(),
        "summary": transaction.summary or f"{invoice.invoice_direction} {invoice.invoice_number}",
        "remark": _combined_remark(transaction, invoice),
        "status": _record_status(record),
        "confidence": record.confidence,
        "businessType": _business_type_label(record.match_method),
        "amount": _format_amount((transaction.credit_amount or Decimal("0")) or (transaction.debit_amount or Decimal("0"))),
        "tax": _format_amount(invoice.tax_amount),
        "directionType": "匹配",
        "transactionCounterparty": transaction.counterparty_name or "-",
        "invoiceCounterparty": _invoice_counterparty(invoice, enterprise_name),
        "payer": _bank_payer(transaction, enterprise_name),
        "payee": _bank_payee(transaction, enterprise_name),
        "seller": invoice.seller_name or "-",
        "buyer": invoice.buyer_name or "-",
        "invoiceNumber": invoice.invoice_number,
        "sourceCompleteness": "流水+发票",
        "confirmType": "match",
        "confirmId": str(record.id),
        "sourceType": "MATCH",
        "sourceId": str(record.id),
        "bankTransactionId": str(transaction.id),
        "invoiceId": str(invoice.id),
    }


def _invoice_only_row(record: MatchRecord, invoice: Invoice, *, enterprise_name: str) -> dict:
    return {
        "id": str(record.id),
        "packageId": str(record.monthly_work_package_id),
        "type": "发票",
        "date": invoice.invoice_date.isoformat(),
        "summary": f"{invoice.invoice_direction} {invoice.invoice_number}",
        "remark": _invoice_remark(invoice),
        "status": _record_status(record),
        "confidence": record.confidence,
        "businessType": _business_type_label(record.match_method),
        "amount": _format_amount(invoice.total_amount),
        "tax": _format_amount(invoice.tax_amount),
        "directionType": _invoice_direction_type(invoice),
        "transactionCounterparty": "-",
        "invoiceCounterparty": _invoice_counterparty(invoice, enterprise_name),
        "payer": "-",
        "payee": "-",
        "seller": invoice.seller_name or "-",
        "buyer": invoice.buyer_name or enterprise_name,
        "invoiceNumber": invoice.invoice_number,
        "sourceCompleteness": "缺失转账主体",
        "confirmType": "match",
        "confirmId": str(record.id),
        "sourceType": "INVOICE",
        "sourceId": str(invoice.id),
        "invoiceId": str(invoice.id),
    }


def _missing_checklist(db: Session, package: MonthlyWorkPackage | None) -> list[dict]:
    if package is None:
        return []
    bank_count = db.query(BankTransaction).filter(BankTransaction.monthly_work_package_id == package.id).count()
    output_count = db.query(Invoice).filter(Invoice.monthly_work_package_id == package.id, Invoice.invoice_direction == "OUTPUT").count()
    input_count = db.query(Invoice).filter(Invoice.monthly_work_package_id == package.id, Invoice.invoice_direction == "INPUT").count()
    ready_report_count = db.query(Report).filter(Report.monthly_work_package_id == package.id, Report.status == "READY").count()
    return [
        {"label": "银行流水", "done": bank_count > 0},
        {"label": "销项明细", "done": output_count > 0},
        {"label": "进项明细", "done": input_count > 0},
        {"label": "人工确认", "done": package.pending_confirmation_count == 0},
        {"label": "健康报告数据", "done": ready_report_count > 0},
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


def _business_type_label(value: str | None) -> str:
    if not value:
        return "待确认"
    return BUSINESS_TYPE_LABELS.get(value, value)


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


def _bank_payer(transaction: BankTransaction, enterprise_name: str) -> str:
    if transaction.debit_amount and transaction.debit_amount != 0:
        return enterprise_name
    if transaction.credit_amount and transaction.credit_amount != 0:
        return transaction.counterparty_name or "-"
    return "-"


def _bank_direction_type(transaction: BankTransaction) -> str:
    if transaction.debit_amount and transaction.debit_amount != 0:
        return "转出"
    if transaction.credit_amount and transaction.credit_amount != 0:
        return "转入"
    return "流水"


def _invoice_direction_type(invoice: Invoice) -> str:
    return "销售" if invoice.invoice_direction == "OUTPUT" else "成本"


def _invoice_counterparty(invoice: Invoice, enterprise_name: str) -> str:
    if invoice.invoice_direction == "OUTPUT":
        return invoice.buyer_name or "-"
    if invoice.seller_name and invoice.seller_name != enterprise_name:
        return invoice.seller_name
    return invoice.buyer_name or "-"


def _bank_payee(transaction: BankTransaction, enterprise_name: str) -> str:
    if transaction.debit_amount and transaction.debit_amount != 0:
        return transaction.counterparty_name or "-"
    if transaction.credit_amount and transaction.credit_amount != 0:
        return enterprise_name
    return "-"


def _invoice_remark(invoice: Invoice) -> str:
    for key in ("备注", "remark", "摘要"):
        value = invoice.raw_row_data.get(key) if invoice.raw_row_data else None
        if value not in (None, ""):
            return str(value)
    return "-"


def _combined_remark(transaction: BankTransaction, invoice: Invoice) -> str:
    parts = []
    if transaction.summary:
        parts.append(transaction.summary)
    invoice_remark = _invoice_remark(invoice)
    if invoice_remark != "-" and invoice_remark not in parts:
        parts.append(invoice_remark)
    return " / ".join(parts) if parts else "-"


def _period(package: MonthlyWorkPackage | None) -> str:
    if package is None:
        return ""
    return f"{package.period_year}-{package.period_month:02d}"


def _format_amount(value) -> str:
    if value in (None, ""):
        return "-"
    return f"{Decimal(str(value)):,.2f}"
