from datetime import date
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.entities import BankTransaction, Enterprise, InitialFinancialSnapshot, MatchRecord, MonthlyWorkPackage


DEFAULT_CHANNEL_ID = UUID("00000000-0000-0000-0000-000000000001")


def create_enterprise(db_session):
    enterprise = Enterprise(
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        name="苏州样例科技有限公司",
        unified_social_credit_code="91320500TEST000001",
        taxpayer_type="GENERAL",
        industry="制造业",
        province="江苏省",
        city="苏州市",
    )
    db_session.add(enterprise)
    db_session.flush()
    return enterprise


def test_enterprise_monthly_package_keeps_org_and_period(db_session):
    enterprise = create_enterprise(db_session)

    snapshot = InitialFinancialSnapshot(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
        balance_sheet_data={"资产总计": 1000000, "负债合计": 400000, "所有者权益合计": 600000},
        income_statement_data={"营业收入": 800000, "净利润": 90000},
        validation_result={"balanced": True},
    )
    package = MonthlyWorkPackage(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
    )
    db_session.add_all([snapshot, package])
    db_session.commit()

    assert package.enterprise_id == enterprise.id
    assert package.organization_id == UUID("00000000-0000-0000-0000-000000000001")
    assert package.period_year == 2026
    assert package.period_month == 5
    assert snapshot.validation_result["balanced"] is True


def test_default_channel_id_is_applied_to_monthly_records(db_session):
    enterprise = create_enterprise(db_session)
    snapshot = InitialFinancialSnapshot(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
    )
    package = MonthlyWorkPackage(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
    )
    db_session.add_all([snapshot, package])
    db_session.flush()

    assert enterprise.channel_id == DEFAULT_CHANNEL_ID
    assert snapshot.channel_id == DEFAULT_CHANNEL_ID
    assert package.channel_id == DEFAULT_CHANNEL_ID


def test_monthly_package_rejects_invalid_period_month(db_session):
    enterprise = create_enterprise(db_session)
    package = MonthlyWorkPackage(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=13,
    )
    db_session.add(package)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_monthly_package_rejects_invalid_completion_percent(db_session):
    enterprise = create_enterprise(db_session)
    package = MonthlyWorkPackage(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
        completion_percent=101,
    )
    db_session.add(package)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_match_record_rejects_invalid_confidence(db_session):
    enterprise = create_enterprise(db_session)
    package = MonthlyWorkPackage(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
    )
    db_session.add(package)
    db_session.flush()

    match = MatchRecord(
        organization_id=enterprise.organization_id,
        monthly_work_package_id=package.id,
        match_method="RULE",
        confidence=101,
    )
    db_session.add(match)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_bank_transaction_rejects_invalid_parse_confidence(db_session):
    enterprise = create_enterprise(db_session)
    package = MonthlyWorkPackage(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
    )
    db_session.add(package)
    db_session.flush()

    transaction = BankTransaction(
        organization_id=enterprise.organization_id,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 1),
        summary="测试流水",
        parse_confidence=101,
    )
    db_session.add(transaction)

    with pytest.raises(IntegrityError):
        db_session.commit()
