from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.database import Base
from app.core.org_context import ensure_default_organization
from app.main import create_app
from app.models.entities import BankTransaction, Enterprise, InitialFinancialSnapshot, MatchRecord, MonthlyWorkPackage
from app.services.enterprise_service import (
    create_enterprise as service_create_enterprise,
    create_monthly_work_package,
    save_initial_snapshot,
)


DEFAULT_CHANNEL_ID = UUID("00000000-0000-0000-0000-000000000001")


def create_test_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    session = TestingSession()
    ensure_default_organization(session)

    app = create_app()

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=False)


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


def test_create_enterprise_initial_snapshot_and_package(db_session):
    enterprise = service_create_enterprise(
        db_session,
        name="苏州初始化测试有限公司",
        unified_social_credit_code="91320500INIT000001",
        taxpayer_type="GENERAL",
        industry="软件和信息技术服务业",
    )
    snapshot = save_initial_snapshot(
        db_session,
        enterprise_id=enterprise.id,
        balance_sheet_data={"资产总计": 500000, "负债合计": 120000, "所有者权益合计": 380000},
        income_statement_data={"营业收入": 200000, "净利润": 30000},
    )
    package = create_monthly_work_package(db_session, enterprise_id=enterprise.id, year=2026, month=5)

    assert snapshot.validation_result == {"balanced": True}
    assert package.data_status == "PENDING_IMPORT"


def test_duplicate_enterprise_returns_409_through_api(db_session):
    client = create_test_client()
    payload = {
        "name": "苏州重复企业有限公司",
        "unified_social_credit_code": "91320500DUP000001",
        "taxpayer_type": "GENERAL",
        "industry": "软件和信息技术服务业",
    }

    assert client.post("/api/enterprises", json=payload).status_code == 201
    response = client.post("/api/enterprises", json=payload)

    assert response.status_code == 409


def test_missing_enterprise_snapshot_returns_404_through_api(db_session):
    client = create_test_client()

    response = client.post(
        f"/api/enterprises/{uuid4()}/initial-snapshot",
        json={
            "balance_sheet_data": {"资产总计": 100, "负债合计": 40, "所有者权益合计": 60},
            "income_statement_data": {"营业收入": 100, "净利润": 10},
        },
    )

    assert response.status_code == 404


def test_duplicate_monthly_package_returns_409_through_api(db_session):
    client = create_test_client()
    enterprise_response = client.post(
        "/api/enterprises",
        json={
            "name": "苏州月包重复有限公司",
            "unified_social_credit_code": "91320500PKG000001",
            "taxpayer_type": "GENERAL",
            "industry": "制造业",
        },
    )
    enterprise_id = enterprise_response.json()["id"]
    payload = {"period_year": 2026, "period_month": 5}

    assert client.post(f"/api/enterprises/{enterprise_id}/monthly-packages", json=payload).status_code == 201
    response = client.post(f"/api/enterprises/{enterprise_id}/monthly-packages", json=payload)

    assert response.status_code == 409


def test_invalid_balance_sheet_value_returns_client_error_through_api(db_session):
    client = create_test_client()
    enterprise_response = client.post(
        "/api/enterprises",
        json={
            "name": "苏州报表错误有限公司",
            "unified_social_credit_code": "91320500BAD000001",
            "taxpayer_type": "GENERAL",
            "industry": "制造业",
        },
    )
    enterprise_id = enterprise_response.json()["id"]

    response = client.post(
        f"/api/enterprises/{enterprise_id}/initial-snapshot",
        json={
            "balance_sheet_data": {"资产总计": "五十万", "负债合计": 120000, "所有者权益合计": 380000},
            "income_statement_data": {"营业收入": 200000, "净利润": 30000},
        },
    )

    assert response.status_code in {400, 422}


def test_non_finite_balance_sheet_value_returns_client_error_through_api(db_session):
    client = create_test_client()
    enterprise_response = client.post(
        "/api/enterprises",
        json={
            "name": "苏州非有限数有限公司",
            "unified_social_credit_code": "91320500NAN00001",
            "taxpayer_type": "GENERAL",
            "industry": "制造业",
        },
    )
    enterprise_id = enterprise_response.json()["id"]

    response = client.post(
        f"/api/enterprises/{enterprise_id}/initial-snapshot",
        json={
            "balance_sheet_data": {"资产总计": "NaN", "负债合计": 120000, "所有者权益合计": 380000},
            "income_statement_data": {"营业收入": 200000, "净利润": 30000},
        },
    )

    assert response.status_code in {400, 422}


def test_duplicate_initial_snapshot_returns_409_through_api(db_session):
    client = create_test_client()
    enterprise_response = client.post(
        "/api/enterprises",
        json={
            "name": "苏州快照重复有限公司",
            "unified_social_credit_code": "91320500SNAP0001",
            "taxpayer_type": "GENERAL",
            "industry": "制造业",
        },
    )
    enterprise_id = enterprise_response.json()["id"]
    payload = {
        "balance_sheet_data": {"资产总计": 500000, "负债合计": 120000, "所有者权益合计": 380000},
        "income_statement_data": {"营业收入": 200000, "净利润": 30000},
    }

    assert client.post(f"/api/enterprises/{enterprise_id}/initial-snapshot", json=payload).status_code == 201
    response = client.post(f"/api/enterprises/{enterprise_id}/initial-snapshot", json=payload)

    assert response.status_code == 409


def test_initial_snapshot_rejects_duplicate_enterprise_at_database_level(db_session):
    enterprise = create_enterprise(db_session)
    first_snapshot = InitialFinancialSnapshot(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
        balance_sheet_data={"资产总计": 500000, "负债合计": 120000, "所有者权益合计": 380000},
        income_statement_data={"营业收入": 200000, "净利润": 30000},
        validation_result={"balanced": True},
    )
    second_snapshot = InitialFinancialSnapshot(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
        balance_sheet_data={"资产总计": 600000, "负债合计": 200000, "所有者权益合计": 400000},
        income_statement_data={"营业收入": 300000, "净利润": 50000},
        validation_result={"balanced": True},
    )
    db_session.add_all([first_snapshot, second_snapshot])

    with pytest.raises(IntegrityError):
        db_session.commit()
