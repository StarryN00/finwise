from uuid import UUID

from app.models.entities import Enterprise, InitialFinancialSnapshot, MonthlyWorkPackage


def test_enterprise_monthly_package_keeps_org_and_period(db_session):
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
