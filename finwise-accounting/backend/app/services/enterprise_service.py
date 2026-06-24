from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.org_context import ensure_default_organization, get_current_organization_id
from app.models.entities import (
    DEFAULT_CHANNEL_ID,
    AccountSubject,
    AccountingLine,
    AuditLog,
    BankTransaction,
    Enterprise,
    HistoricalBalanceRow,
    HistoricalImportBatch,
    HistoricalLedgerEntry,
    ImportBatch,
    InitialFinancialSnapshot,
    Invoice,
    MatchRecord,
    MatchingRule,
    MonthlyStatement,
    MonthlyWorkPackage,
    Report,
    TaxFilingDraft,
    TechnologyProfile,
    TechnologyScanJobItem,
    TechnologyTag,
    Voucher,
    VoucherEntry,
    VoucherRule,
)


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
    name = _required_text(name, "请填写企业名称。")
    unified_social_credit_code = _required_text(
        unified_social_credit_code,
        "请填写统一社会信用代码。",
    )
    taxpayer_type = _required_text(taxpayer_type, "请选择纳税人类型。")
    industry = _required_text(industry, "请选择所属行业。")
    existing = db.scalar(
        select(Enterprise).where(
            Enterprise.organization_id == organization_id,
            Enterprise.unified_social_credit_code == unified_social_credit_code,
        )
    )
    if existing is not None:
        raise ConflictError("该统一社会信用代码已存在，请检查是否已保存过该企业。")

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
        raise ConflictError("该统一社会信用代码已存在，请检查是否已保存过该企业。") from exc
    db.refresh(enterprise)
    return enterprise


def _required_text(value: str, message: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ValidationError(message)
    return normalized


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
        raise ConflictError("该企业的期初数据已保存，请勿重复提交。")

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
        raise ConflictError("期初数据保存失败，请刷新后重试。") from exc
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
        raise ConflictError("该企业当前期间的工作包已存在，请勿重复创建。")

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
        raise ConflictError("该企业当前期间的工作包已存在，请勿重复创建。") from exc
    db.refresh(package)
    return package


def delete_enterprise(db: Session, *, enterprise_id: UUID) -> None:
    organization_id = _ensure_current_organization(db)
    enterprise = _get_enterprise_in_current_organization(db, enterprise_id, organization_id)
    package_ids = list(
        db.scalars(
            select(MonthlyWorkPackage.id).where(
                MonthlyWorkPackage.organization_id == organization_id,
                MonthlyWorkPackage.enterprise_id == enterprise.id,
            )
        )
    )
    historical_batch_ids = list(
        db.scalars(
            select(HistoricalImportBatch.id).where(
                HistoricalImportBatch.organization_id == organization_id,
                HistoricalImportBatch.enterprise_id == enterprise.id,
            )
        )
    )
    profile_ids = list(
        db.scalars(
            select(TechnologyProfile.id).where(
                TechnologyProfile.organization_id == organization_id,
                TechnologyProfile.enterprise_id == enterprise.id,
            )
        )
    )
    voucher_ids: list[UUID] = []
    if package_ids:
        voucher_ids = list(
            db.scalars(
                select(Voucher.id).where(
                    Voucher.organization_id == organization_id,
                    Voucher.monthly_work_package_id.in_(package_ids),
                )
            )
        )

    try:
        if voucher_ids:
            _delete_by(db, VoucherEntry, VoucherEntry.voucher_id.in_(voucher_ids))

        if package_ids:
            for model in [
                MatchRecord,
                AccountingLine,
                Voucher,
                MonthlyStatement,
                TaxFilingDraft,
                Report,
                AuditLog,
                BankTransaction,
                Invoice,
                ImportBatch,
            ]:
                _delete_by(db, model, model.monthly_work_package_id.in_(package_ids))
            _delete_by(db, MonthlyWorkPackage, MonthlyWorkPackage.id.in_(package_ids))

        if historical_batch_ids:
            _delete_by(db, HistoricalLedgerEntry, HistoricalLedgerEntry.import_batch_id.in_(historical_batch_ids))
            _delete_by(db, HistoricalBalanceRow, HistoricalBalanceRow.import_batch_id.in_(historical_batch_ids))
        _delete_by(db, HistoricalLedgerEntry, HistoricalLedgerEntry.enterprise_id == enterprise.id)
        _delete_by(db, HistoricalBalanceRow, HistoricalBalanceRow.enterprise_id == enterprise.id)
        _delete_by(db, HistoricalImportBatch, HistoricalImportBatch.enterprise_id == enterprise.id)

        _delete_by(db, InitialFinancialSnapshot, InitialFinancialSnapshot.enterprise_id == enterprise.id)
        _delete_by(db, AccountSubject, AccountSubject.enterprise_id == enterprise.id)
        _delete_by(db, VoucherRule, VoucherRule.enterprise_id == enterprise.id)
        _delete_by(db, MatchingRule, MatchingRule.enterprise_id == enterprise.id)
        _delete_by(db, TechnologyScanJobItem, TechnologyScanJobItem.enterprise_id == enterprise.id)
        _delete_by(db, TechnologyTag, TechnologyTag.enterprise_id == enterprise.id)
        if profile_ids:
            _delete_by(db, TechnologyProfile, TechnologyProfile.id.in_(profile_ids))
        db.delete(enterprise)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("企业已有相关业务数据，无法直接删除。") from exc


def _is_balance_sheet_balanced(data: dict[str, Any]) -> bool:
    assets = _statement_decimal(data, "资产总计")
    liabilities = _statement_decimal(data, "负债合计")
    equity = _statement_decimal(data, "所有者权益合计")
    return abs(assets - liabilities - equity) < Decimal("0.01")


def _delete_by(db: Session, model: type[Any], condition: Any) -> None:
    db.execute(delete(model).where(condition))


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
        raise NotFoundError("当前机构下未找到该企业。")
    return enterprise


def _statement_decimal(data: dict[str, Any], field_name: str) -> Decimal:
    value = data.get(field_name, 0)
    if value in (None, ""):
        return Decimal("0")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"财务报表字段“{field_name}”必须是数字。") from exc
    if not decimal_value.is_finite():
        raise ValidationError(f"财务报表字段“{field_name}”必须是有效数字。")
    return decimal_value
