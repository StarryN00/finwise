from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.database import Base
from app.core.org_context import ensure_default_organization
from app.main import create_app
from app.models import AccountingLine, BankTransaction, Enterprise, Invoice, MatchingRule, MonthlyWorkPackage
from app.services.matching_service import run_matching


ORG = UUID("00000000-0000-0000-0000-000000000001")


def make_context():
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
    db_session = TestingSession()
    ensure_default_organization(db_session)
    app = create_app(init_db_on_startup=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=False), db_session


def make_package(db_session):
    enterprise = Enterprise(
        organization_id=ORG,
        name="苏州操作闭环测试有限公司",
        unified_social_credit_code="91320500FLOW000001",
        taxpayer_type="GENERAL",
        industry="制造业",
    )
    db_session.add(enterprise)
    db_session.flush()
    package = MonthlyWorkPackage(
        organization_id=ORG,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
    )
    db_session.add(package)
    db_session.commit()
    return enterprise, package


def add_unmatched_bank_transaction(db_session, package):
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 8),
        summary="支付测试咨询款项",
        debit_amount=Decimal("880.00"),
        credit_amount=Decimal("0.00"),
        counterparty_name="苏州咨询服务有限公司",
    )
    db_session.add(transaction)
    db_session.commit()
    return transaction


def add_unmatched_invoice(db_session, package):
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-UNMATCHED",
        invoice_date=date(2026, 5, 9),
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
    )
    db_session.add(invoice)
    db_session.commit()
    return invoice


def test_workspace_rows_merge_bank_and_invoice_sources():
    client, db_session = make_context()
    enterprise, package = make_package(db_session)
    matched_transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 8),
        summary="收到客户货款 备注A",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("1130.00"),
        counterparty_name="苏州客户有限公司",
    )
    unmatched_transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 10),
        summary="支付零星采购",
        debit_amount=Decimal("500.00"),
        credit_amount=Decimal("0.00"),
        counterparty_name="苏州供应商有限公司",
    )
    matched_invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-MATCHED",
        invoice_date=date(2026, 5, 9),
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
        seller_name=enterprise.name,
        buyer_name="苏州客户有限公司",
        raw_row_data={"备注": "发票备注A"},
    )
    unmatched_invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="INPUT",
        invoice_number="IN-ONLY",
        invoice_date=date(2026, 5, 11),
        amount=Decimal("800.00"),
        tax_amount=Decimal("48.00"),
        total_amount=Decimal("848.00"),
        seller_name="苏州票方有限公司",
        buyer_name=enterprise.name,
        raw_row_data={"备注": "票据备注B"},
    )
    db_session.add_all([matched_transaction, unmatched_transaction, matched_invoice, unmatched_invoice])
    db_session.commit()
    run_matching(db_session, monthly_work_package_id=package.id)

    response = client.get("/api/workspace")

    assert response.status_code == 200
    rows = response.json()["accountRows"]
    merged_row = next(row for row in rows if row["invoiceNumber"] == "OUT-MATCHED")
    assert merged_row["type"] == "流水+发票"
    assert merged_row["sourceCompleteness"] == "流水+发票"
    assert merged_row["payer"] == "苏州客户有限公司"
    assert merged_row["payee"] == enterprise.name
    assert merged_row["seller"] == enterprise.name
    assert merged_row["buyer"] == "苏州客户有限公司"
    assert merged_row["remark"] == "收到客户货款 备注A / 发票备注A"
    assert merged_row["amount"] == "1,130.00"
    assert merged_row["tax"] == "130.00"

    bank_only_row = next(row for row in rows if row["sourceId"] == str(unmatched_transaction.id))
    assert bank_only_row["sourceCompleteness"] == "缺失发票主体"
    assert bank_only_row["payer"] == enterprise.name
    assert bank_only_row["payee"] == "苏州供应商有限公司"
    assert bank_only_row["seller"] == "-"
    assert bank_only_row["buyer"] == "-"

    invoice_only_row = next(row for row in rows if row["sourceId"] == str(unmatched_invoice.id))
    assert invoice_only_row["sourceCompleteness"] == "缺失转账主体"
    assert invoice_only_row["payer"] == "-"
    assert invoice_only_row["payee"] == "-"
    assert invoice_only_row["seller"] == "苏州票方有限公司"
    assert invoice_only_row["buyer"] == enterprise.name
    assert invoice_only_row["remark"] == "票据备注B"


def test_workspace_rows_expose_confirmation_handles():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    transaction = add_unmatched_bank_transaction(db_session, package)
    invoice = add_unmatched_invoice(db_session, package)
    run_matching(db_session, monthly_work_package_id=package.id)

    response = client.get("/api/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["workPackages"][0]["id"] == str(package.id)
    bank_row = next(row for row in payload["accountRows"] if row["type"] == "流水")
    invoice_row = next(row for row in payload["accountRows"] if row["type"] == "发票")
    assert bank_row["packageId"] == str(package.id)
    assert bank_row["confirmType"] == "unmatched"
    assert bank_row["sourceType"] == "BANK_TRANSACTION"
    assert bank_row["sourceId"] == str(transaction.id)
    assert invoice_row["confirmType"] == "unmatched"
    assert invoice_row["sourceType"] == "INVOICE"
    assert invoice_row["sourceId"] == str(invoice.id)


def test_workspace_snapshot_can_focus_selected_package():
    client, db_session = make_context()
    first_enterprise, first_package = make_package(db_session)
    first_transaction = add_unmatched_bank_transaction(db_session, first_package)
    second_enterprise = Enterprise(
        organization_id=ORG,
        name="苏州第二主体有限公司",
        unified_social_credit_code="91320500FLOW000002",
        taxpayer_type="GENERAL",
        industry="服务业",
    )
    db_session.add(second_enterprise)
    db_session.flush()
    second_package = MonthlyWorkPackage(
        organization_id=ORG,
        enterprise_id=second_enterprise.id,
        period_year=2026,
        period_month=4,
    )
    db_session.add(second_package)
    db_session.commit()
    second_transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=second_package.id,
        transaction_date=date(2026, 4, 8),
        summary="第二主体流水",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("200.00"),
        counterparty_name="第二主体客户",
    )
    db_session.add(second_transaction)
    db_session.commit()

    response = client.get(f"/api/workspace?package_id={second_package.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selectedPackageId"] == str(second_package.id)
    assert payload["currentPeriod"] == "2026-04"
    assert [row["sourceId"] for row in payload["accountRows"]] == [str(second_transaction.id)]
    assert str(first_transaction.id) not in [row["sourceId"] for row in payload["accountRows"]]
    assert payload["workPackages"][0]["company"] == first_enterprise.name


def test_confirm_unmatched_bank_transaction_creates_confirmed_line_and_rule():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    transaction = add_unmatched_bank_transaction(db_session, package)
    run_matching(db_session, monthly_work_package_id=package.id)

    response = client.post(
        f"/api/monthly-packages/{package.id}/confirm-unmatched",
        json={
            "source_type": "BANK_TRANSACTION",
            "source_id": str(transaction.id),
            "business_type": "CONSULTING_SERVICE",
            "save_as_rule": True,
        },
    )

    assert response.status_code == 200
    db_session.refresh(package)
    line = db_session.query(AccountingLine).one()
    rule = db_session.query(MatchingRule).one()
    assert package.pending_confirmation_count == 0
    assert line.confirmation_status == "CONFIRMED"
    assert line.business_type == "CONSULTING_SERVICE"
    assert rule.suggested_business_type == "CONSULTING_SERVICE"


def test_ai_matching_endpoint_runs_ai_suggestions(monkeypatch):
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)

    def fake_run_ai_matching(db, *, monthly_work_package_id):
        assert db is db_session
        assert monthly_work_package_id == package.id
        return {
            "created_matches": 2,
            "uncertain_matches": 3,
            "candidate_transactions": 8,
            "candidate_invoices": 9,
            "pending_confirmations": 5,
        }

    monkeypatch.setattr("app.api.matching.run_ai_matching", fake_run_ai_matching)

    response = client.post(f"/api/monthly-packages/{package.id}/matching/ai-run")

    assert response.status_code == 200
    assert response.json()["created_matches"] == 2
    assert response.json()["uncertain_matches"] == 3


def test_confirm_unmatched_invoice_marks_invoice_confirmed():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    invoice = add_unmatched_invoice(db_session, package)
    run_matching(db_session, monthly_work_package_id=package.id)

    response = client.post(
        f"/api/monthly-packages/{package.id}/confirm-unmatched",
        json={
            "source_type": "INVOICE",
            "source_id": str(invoice.id),
            "business_type": "OUTPUT_REVENUE",
        },
    )

    assert response.status_code == 200
    db_session.refresh(package)
    assert package.pending_confirmation_count == 0
    assert response.json()["confirmation_status"] == "CONFIRMED"


def test_rules_api_creates_lists_and_deletes_enterprise_rules():
    client, db_session = make_context()
    enterprise, _package = make_package(db_session)

    create_response = client.post(
        "/api/rules",
        json={
            "enterprise_id": str(enterprise.id),
            "summary_keywords": ["咨询"],
            "counterparty_pattern": "服务",
            "suggested_business_type": "CONSULTING_SERVICE",
            "invoice_direction": "INPUT",
        },
    )
    assert create_response.status_code == 201
    rule_id = create_response.json()["id"]

    list_response = client.get(f"/api/rules?enterprise_id={enterprise.id}")
    assert list_response.status_code == 200
    assert [rule["id"] for rule in list_response.json()] == [rule_id]

    delete_response = client.delete(f"/api/rules/{rule_id}")
    assert delete_response.status_code == 204
    assert db_session.query(MatchingRule).count() == 0
