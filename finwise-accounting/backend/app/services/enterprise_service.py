from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.org_context import ensure_default_organization, get_current_organization_id
from app.models.entities import DEFAULT_CHANNEL_ID, Enterprise, InitialFinancialSnapshot, MonthlyWorkPackage


def create_enterprise(
    db: Session,
    *,
    name: str,
    unified_social_credit_code: str,
    taxpayer_type: str,
    industry: str,
    province: str = "江苏省",
    city: str = "苏州市",
) -> Enterprise:
    ensure_default_organization(db)
    enterprise = Enterprise(
        channel_id=DEFAULT_CHANNEL_ID,
        organization_id=get_current_organization_id(),
        name=name,
        unified_social_credit_code=unified_social_credit_code,
        taxpayer_type=taxpayer_type,
        industry=industry,
        province=province,
        city=city,
    )
    db.add(enterprise)
    db.commit()
    db.refresh(enterprise)
    return enterprise


def save_initial_snapshot(
    db: Session,
    *,
    enterprise_id: UUID,
    balance_sheet_data: dict[str, Any],
    income_statement_data: dict[str, Any],
) -> InitialFinancialSnapshot:
    ensure_default_organization(db)
    snapshot = InitialFinancialSnapshot(
        channel_id=DEFAULT_CHANNEL_ID,
        organization_id=get_current_organization_id(),
        enterprise_id=enterprise_id,
        balance_sheet_data=balance_sheet_data,
        income_statement_data=income_statement_data,
        validation_result={"balanced": _is_balance_sheet_balanced(balance_sheet_data)},
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def create_monthly_work_package(
    db: Session,
    *,
    enterprise_id: UUID,
    year: int,
    month: int,
) -> MonthlyWorkPackage:
    ensure_default_organization(db)
    package = MonthlyWorkPackage(
        channel_id=DEFAULT_CHANNEL_ID,
        organization_id=get_current_organization_id(),
        enterprise_id=enterprise_id,
        period_year=year,
        period_month=month,
    )
    db.add(package)
    db.commit()
    db.refresh(package)
    return package


def _is_balance_sheet_balanced(data: dict[str, Any]) -> bool:
    assets = float(data.get("资产总计", 0) or 0)
    liabilities = float(data.get("负债合计", 0) or 0)
    equity = float(data.get("所有者权益合计", 0) or 0)
    return abs(assets - liabilities - equity) < 0.01
