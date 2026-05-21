from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.org_context import ensure_default_organization, get_current_organization_id
from app.models.entities import DEFAULT_CHANNEL_ID, Enterprise, InitialFinancialSnapshot, MonthlyWorkPackage


class EnterpriseWorkflowError(Exception):
    """Base exception for enterprise initialization domain errors."""


class NotFoundError(EnterpriseWorkflowError):
    pass


class ConflictError(EnterpriseWorkflowError):
    pass


class ValidationError(EnterpriseWorkflowError):
    pass


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
    organization_id = _ensure_current_organization(db)
    existing = db.scalar(
        select(Enterprise).where(
            Enterprise.organization_id == organization_id,
            Enterprise.unified_social_credit_code == unified_social_credit_code,
        )
    )
    if existing is not None:
        raise ConflictError("Enterprise unified social credit code already exists in this organization.")

    enterprise = Enterprise(
        channel_id=DEFAULT_CHANNEL_ID,
        organization_id=organization_id,
        name=name,
        unified_social_credit_code=unified_social_credit_code,
        taxpayer_type=taxpayer_type,
        industry=industry,
        province=province,
        city=city,
    )
    db.add(enterprise)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Enterprise unified social credit code already exists in this organization.") from exc
    db.refresh(enterprise)
    return enterprise


def save_initial_snapshot(
    db: Session,
    *,
    enterprise_id: UUID,
    balance_sheet_data: dict[str, Any],
    income_statement_data: dict[str, Any],
) -> InitialFinancialSnapshot:
    organization_id = _ensure_current_organization(db)
    _get_enterprise_in_current_organization(db, enterprise_id, organization_id)

    existing_snapshot = db.scalar(
        select(InitialFinancialSnapshot).where(
            InitialFinancialSnapshot.organization_id == organization_id,
            InitialFinancialSnapshot.enterprise_id == enterprise_id,
        )
    )
    if existing_snapshot is not None:
        raise ConflictError("Initial financial snapshot already exists for this enterprise.")

    snapshot = InitialFinancialSnapshot(
        channel_id=DEFAULT_CHANNEL_ID,
        organization_id=organization_id,
        enterprise_id=enterprise_id,
        balance_sheet_data=balance_sheet_data,
        income_statement_data=income_statement_data,
        validation_result={"balanced": _is_balance_sheet_balanced(balance_sheet_data)},
    )
    db.add(snapshot)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Initial financial snapshot could not be saved.") from exc
    db.refresh(snapshot)
    return snapshot


def create_monthly_work_package(
    db: Session,
    *,
    enterprise_id: UUID,
    year: int,
    month: int,
) -> MonthlyWorkPackage:
    organization_id = _ensure_current_organization(db)
    _get_enterprise_in_current_organization(db, enterprise_id, organization_id)

    existing_package = db.scalar(
        select(MonthlyWorkPackage).where(
            MonthlyWorkPackage.organization_id == organization_id,
            MonthlyWorkPackage.enterprise_id == enterprise_id,
            MonthlyWorkPackage.period_year == year,
            MonthlyWorkPackage.period_month == month,
        )
    )
    if existing_package is not None:
        raise ConflictError("Monthly work package already exists for this enterprise and period.")

    package = MonthlyWorkPackage(
        channel_id=DEFAULT_CHANNEL_ID,
        organization_id=organization_id,
        enterprise_id=enterprise_id,
        period_year=year,
        period_month=month,
    )
    db.add(package)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Monthly work package already exists for this enterprise and period.") from exc
    db.refresh(package)
    return package


def _is_balance_sheet_balanced(data: dict[str, Any]) -> bool:
    assets = _statement_decimal(data, "资产总计")
    liabilities = _statement_decimal(data, "负债合计")
    equity = _statement_decimal(data, "所有者权益合计")
    return abs(assets - liabilities - equity) < Decimal("0.01")


def _ensure_current_organization(db: Session) -> UUID:
    ensure_default_organization(db)
    return get_current_organization_id()


def _get_enterprise_in_current_organization(
    db: Session,
    enterprise_id: UUID,
    organization_id: UUID,
) -> Enterprise:
    enterprise = db.get(Enterprise, enterprise_id)
    if enterprise is None or enterprise.organization_id != organization_id:
        raise NotFoundError("Enterprise not found in current organization.")
    return enterprise


def _statement_decimal(data: dict[str, Any], field_name: str) -> Decimal:
    value = data.get(field_name, 0)
    if value in (None, ""):
        return Decimal("0")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"Financial statement field '{field_name}' must be numeric.") from exc
    if not decimal_value.is_finite():
        raise ValidationError(f"Financial statement field '{field_name}' must be a finite number.")
    return decimal_value
