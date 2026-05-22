from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.org_context import get_current_organization_id
from app.models import Enterprise, MonthlyStatement, MonthlyWorkPackage, Report, TaxFilingDraft
from app.reports.health_diagnosis import build_health_diagnosis


class ReportDomainError(Exception):
    pass


class MonthlyPackageNotFoundError(ReportDomainError):
    pass


def generate_health_report(db: Session, *, monthly_work_package_id: UUID, output_dir: Path | None = None) -> Report:
    package = _get_monthly_package(db, monthly_work_package_id)
    enterprise = db.get(Enterprise, package.enterprise_id)
    statement = db.scalar(select(MonthlyStatement).where(MonthlyStatement.monthly_work_package_id == package.id))
    tax_draft = db.scalar(select(TaxFilingDraft).where(TaxFilingDraft.monthly_work_package_id == package.id))
    period = f"{package.period_year}-{package.period_month:02d}"

    diagnosis = build_health_diagnosis(
        enterprise={"name": enterprise.name if enterprise else "未命名企业", "industry": enterprise.industry if enterprise else ""},
        period=period,
        statement={
            "estimated_balance_sheet": statement.estimated_balance_sheet if statement else {},
            "estimated_income_statement": statement.estimated_income_statement if statement else {},
        },
        tax_draft=tax_draft.data if tax_draft else {},
    )

    output_dir = output_dir or get_settings().upload_dir / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"health-report-{package.id}.html"
    html_path.write_text(diagnosis["html"], encoding="utf-8")

    report = db.scalar(
        select(Report).where(
            Report.monthly_work_package_id == package.id,
            Report.report_type == "FINANCIAL_HEALTH",
        )
    )
    if report is None:
        report = Report(
            organization_id=package.organization_id,
            monthly_work_package_id=package.id,
            report_type="FINANCIAL_HEALTH",
        )
        db.add(report)

    report.data_version = {
        "period": period,
        "missing_data": diagnosis["missing_data"],
        "source": "confirmed_monthly_data",
    }
    report.html_path = str(html_path)
    report.status = diagnosis["status"]
    db.commit()
    db.refresh(report)
    return report


def desensitize_ai_payload(payload: dict) -> dict:
    sanitized = {}
    sensitive_names = [str(payload.get("enterprise_name", "")), str(payload.get("counterparty_name", ""))]
    for key, value in payload.items():
        if key in {"enterprise_name", "tax_number", "unified_social_credit_code"}:
            continue
        if key == "counterparty_name":
            sanitized[key] = _mask_company_name(str(value))
            continue
        if key == "summary":
            sanitized[key] = _sanitize_summary(str(value), sensitive_names)
            continue
        sanitized[key] = value
    return sanitized


def _get_monthly_package(db: Session, monthly_work_package_id: UUID) -> MonthlyWorkPackage:
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None or package.organization_id != get_current_organization_id():
        raise MonthlyPackageNotFoundError("Monthly work package not found.")
    return package


def _mask_company_name(name: str) -> str:
    normalized = name.strip()
    if len(normalized) >= 2:
        return f"{normalized[:2]}***公司"
    return "***公司"


def _sanitize_summary(summary: str, sensitive_names: list[str]) -> str:
    sanitized = summary
    for name in sensitive_names:
        for fragment in _sensitive_name_fragments(name):
            sanitized = sanitized.replace(fragment, "交易对手")
    sanitized = re.sub(r"9[0-9A-Z]{10,}", "税号", sanitized)
    return sanitized


def _sensitive_name_fragments(name: str) -> list[str]:
    normalized = name.strip()
    if not normalized:
        return []
    fragments = [normalized]
    for suffix in ("有限责任公司", "股份有限公司", "有限公司", "公司"):
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            fragments.append(normalized[: -len(suffix)])
            break
    return fragments
