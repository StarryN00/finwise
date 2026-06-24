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
from app.models.entities import (
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
    TechnologyScanJob,
    TechnologyScanJobItem,
    TechnologyTag,
    Voucher,
    VoucherEntry,
    VoucherRule,
)
from app.services.enterprise_service import (
    create_enterprise as service_create_enterprise,
    create_monthly_work_package,
    delete_enterprise,
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

    app = create_app(init_db_on_startup=False)

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


def test_delete_enterprise_removes_all_related_records(db_session):
    enterprise = create_enterprise(db_session)
    package = MonthlyWorkPackage(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
    )
    historical_batch = HistoricalImportBatch(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
        fiscal_year=2025,
        ledger_filename="ledger.xlsx",
        balance_filename="balance.xlsx",
    )
    scan_job = TechnologyScanJob(organization_id=enterprise.organization_id, provider="QICHACHA")
    db_session.add_all([package, historical_batch, scan_job])
    db_session.flush()

    import_batch = ImportBatch(
        organization_id=enterprise.organization_id,
        monthly_work_package_id=package.id,
        file_type="BANK",
        original_filename="bank.xlsx",
        stored_path="/tmp/bank.xlsx",
    )
    bank_transaction = BankTransaction(
        organization_id=enterprise.organization_id,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 1),
        summary="银行流水",
    )
    invoice = Invoice(
        organization_id=enterprise.organization_id,
        monthly_work_package_id=package.id,
        invoice_direction="INPUT",
        invoice_number="INV-001",
        invoice_date=date(2026, 5, 1),
        amount=100,
        tax_amount=13,
        total_amount=113,
    )
    voucher = Voucher(
        organization_id=enterprise.organization_id,
        monthly_work_package_id=package.id,
        voucher_date=date(2026, 5, 1),
        summary="测试凭证",
        source_key="test-source",
    )
    profile = TechnologyProfile(organization_id=enterprise.organization_id, enterprise_id=enterprise.id)
    db_session.add_all([import_batch, bank_transaction, invoice, voucher, profile])
    db_session.flush()

    db_session.add_all(
        [
            InitialFinancialSnapshot(
                organization_id=enterprise.organization_id,
                enterprise_id=enterprise.id,
                balance_sheet_data={"资产总计": 100},
                income_statement_data={"营业收入": 100},
            ),
            MatchRecord(
                organization_id=enterprise.organization_id,
                monthly_work_package_id=package.id,
                bank_transaction_id=bank_transaction.id,
                invoice_id=invoice.id,
                match_method="RULE",
            ),
            AccountingLine(
                organization_id=enterprise.organization_id,
                monthly_work_package_id=package.id,
                source_type="BANK",
                source_id=str(bank_transaction.id),
                business_type="FEE",
                direction="PAYMENT",
                amount=100,
                include_category="INCLUDE",
            ),
            VoucherEntry(
                organization_id=enterprise.organization_id,
                voucher_id=voucher.id,
                line_no=1,
                direction="DEBIT",
                account_code="5602",
                account_name="管理费用",
                amount=100,
                source_type="BANK",
                source_id=str(bank_transaction.id),
            ),
            MonthlyStatement(
                organization_id=enterprise.organization_id,
                monthly_work_package_id=package.id,
            ),
            TaxFilingDraft(
                organization_id=enterprise.organization_id,
                monthly_work_package_id=package.id,
            ),
            Report(
                organization_id=enterprise.organization_id,
                monthly_work_package_id=package.id,
                report_type="HEALTH",
            ),
            AuditLog(
                organization_id=enterprise.organization_id,
                monthly_work_package_id=package.id,
                action="TEST",
            ),
            AccountSubject(
                organization_id=enterprise.organization_id,
                enterprise_id=enterprise.id,
                code="1002",
                name="银行存款",
                category="ASSET",
                normal_balance="DEBIT",
            ),
            HistoricalLedgerEntry(
                organization_id=enterprise.organization_id,
                enterprise_id=enterprise.id,
                import_batch_id=historical_batch.id,
                fiscal_year=2025,
                voucher_date=date(2025, 1, 1),
                voucher_no="记-001",
                summary="历史凭证",
                account_full_name="银行存款",
                account_code="1002",
                account_name="银行存款",
            ),
            HistoricalBalanceRow(
                organization_id=enterprise.organization_id,
                enterprise_id=enterprise.id,
                import_batch_id=historical_batch.id,
                fiscal_year=2025,
                account_code="1002",
                account_name="银行存款",
            ),
            VoucherRule(
                organization_id=enterprise.organization_id,
                enterprise_id=enterprise.id,
                rule_name="测试规则",
                summary_template="测试",
                debit_account_code="5602",
                credit_account_code="1002",
            ),
            MatchingRule(
                organization_id=enterprise.organization_id,
                enterprise_id=enterprise.id,
                scope="ENTERPRISE",
                suggested_business_type="FEE",
            ),
            TechnologyTag(
                organization_id=enterprise.organization_id,
                enterprise_id=enterprise.id,
                profile_id=profile.id,
                category="科技型企业认定",
                name="高新技术企业",
                source_provider="QICHACHA",
            ),
            TechnologyScanJobItem(
                organization_id=enterprise.organization_id,
                job_id=scan_job.id,
                enterprise_id=enterprise.id,
                enterprise_name=enterprise.name,
            ),
        ]
    )
    db_session.commit()

    delete_enterprise(db_session, enterprise_id=enterprise.id)

    for model in [
        Enterprise,
        InitialFinancialSnapshot,
        MonthlyWorkPackage,
        ImportBatch,
        BankTransaction,
        Invoice,
        MatchRecord,
        AccountingLine,
        Voucher,
        VoucherEntry,
        MonthlyStatement,
        TaxFilingDraft,
        Report,
        AuditLog,
        AccountSubject,
        HistoricalImportBatch,
        HistoricalLedgerEntry,
        HistoricalBalanceRow,
        VoucherRule,
        MatchingRule,
        TechnologyProfile,
        TechnologyTag,
        TechnologyScanJobItem,
    ]:
        assert db_session.query(model).count() == 0
    assert db_session.query(TechnologyScanJob).count() == 1


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
    assert response.json()["detail"] == "该统一社会信用代码已存在，请检查是否已保存过该企业。"


def test_delete_enterprise_endpoint_returns_204_and_404_after_delete(db_session):
    client = create_test_client()
    enterprise_response = client.post(
        "/api/enterprises",
        json={
            "name": "苏州待删除企业有限公司",
            "unified_social_credit_code": "91320500DEL00001",
            "taxpayer_type": "GENERAL",
            "industry": "制造业",
        },
    )
    enterprise_id = enterprise_response.json()["id"]

    assert client.delete(f"/api/enterprises/{enterprise_id}").status_code == 204
    assert client.delete(f"/api/enterprises/{enterprise_id}").status_code == 404


def test_blank_enterprise_name_returns_400_through_api(db_session):
    client = create_test_client()

    response = client.post(
        "/api/enterprises",
        json={
            "name": " ",
            "unified_social_credit_code": "91320500REQ000001",
            "taxpayer_type": "GENERAL",
            "industry": "制造业",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "请填写企业名称。"


def test_blank_unified_social_credit_code_returns_400_through_api(db_session):
    client = create_test_client()

    response = client.post(
        "/api/enterprises",
        json={
            "name": "苏州必填校验有限公司",
            "unified_social_credit_code": " ",
            "taxpayer_type": "GENERAL",
            "industry": "制造业",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "请填写统一社会信用代码。"


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
    assert response.json()["detail"] == "该企业当前期间的工作包已存在，请勿重复创建。"


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
    assert response.json()["detail"] == "该企业的期初数据已保存，请勿重复提交。"


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
