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
from app.models import Enterprise, HistoricalImportBatch, HistoricalLedgerEntry, MonthlyWorkPackage, Voucher, VoucherEntry


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
        name="苏州账簿接口测试有限公司",
        unified_social_credit_code="91320500LEDGERAPI1",
        taxpayer_type="GENERAL",
        industry="制造业",
    )
    db_session.add(enterprise)
    db_session.flush()
    package = MonthlyWorkPackage(
        organization_id=ORG,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=4,
    )
    db_session.add(package)
    db_session.commit()
    return package


def add_voucher(db_session, package, *, number, voucher_date, status, entries):
    voucher = Voucher(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        voucher_date=voucher_date,
        voucher_number=number,
        summary=f"摘要{number or '未编号'}",
        source_key=f"ledger-api:{number or 'pending'}:{voucher_date.isoformat()}:{len(entries)}",
        source_data={},
        ai_confidence=90,
        status=status,
    )
    db_session.add(voucher)
    db_session.flush()
    for line_no, (direction, account_code, account_name, amount) in enumerate(entries, start=1):
        db_session.add(
            VoucherEntry(
                organization_id=ORG,
                voucher_id=voucher.id,
                line_no=line_no,
                direction=direction,
                account_code=account_code,
                account_name=account_name,
                amount=Decimal(amount),
                source_type="TEST",
                source_id=f"{voucher.id}:{line_no}",
            )
        )
    db_session.commit()
    return voucher


def add_historical_entry(db_session, package):
    batch = HistoricalImportBatch(
        organization_id=ORG,
        enterprise_id=package.enterprise_id,
        fiscal_year=2026,
        period_start_month=1,
        period_end_month=3,
        ledger_filename="ledger.xlsx",
        balance_filename="balance.xlsx",
    )
    db_session.add(batch)
    db_session.flush()
    db_session.add(
        HistoricalLedgerEntry(
            organization_id=ORG,
            enterprise_id=package.enterprise_id,
            import_batch_id=batch.id,
            fiscal_year=2026,
            period_start_month=1,
            period_end_month=3,
            voucher_date=date(2026, 3, 31),
            voucher_no="记-0001",
            summary="历史销售",
            account_full_name="主营业务收入",
            account_code="5001",
            account_name="主营业务收入",
            debit_amount=Decimal("0.00"),
            credit_amount=Decimal("100.00"),
        )
    )
    db_session.commit()


def seed_ledgers(db_session, package):
    add_voucher(
        db_session,
        package,
        number="记-0001",
        voucher_date=date(2026, 4, 1),
        status="CONFIRMED",
        entries=[
            ("DEBIT", "1002", "银行存款", "200.00"),
            ("CREDIT", "5001", "主营业务收入", "200.00"),
        ],
    )
    add_voucher(
        db_session,
        package,
        number=None,
        voucher_date=date(2026, 4, 2),
        status="PENDING_CONFIRMATION",
        entries=[
            ("DEBIT", "560203", "服务费", "50.00"),
            ("CREDIT", "1002", "银行存款", "50.00"),
        ],
    )


def test_ledger_summary_endpoint_counts_confirmed_and_pending_vouchers():
    client, db_session = make_context()
    package = make_package(db_session)
    seed_ledgers(db_session, package)

    response = client.get(f"/api/monthly-packages/{package.id}/ledgers/summary")

    assert response.status_code == 200
    assert response.json() == {
        "confirmed_voucher_count": 1,
        "pending_voucher_count": 1,
        "entry_count": 2,
        "is_final": False,
    }


def test_ledger_endpoints_return_only_confirmed_voucher_data():
    client, db_session = make_context()
    package = make_package(db_session)
    seed_ledgers(db_session, package)

    journal = client.get(f"/api/monthly-packages/{package.id}/ledgers/journal")
    general = client.get(f"/api/monthly-packages/{package.id}/ledgers/general")
    detail = client.get(f"/api/monthly-packages/{package.id}/ledgers/detail", params={"account_code": "1002"})
    trial = client.get(f"/api/monthly-packages/{package.id}/ledgers/trial-balance")
    accounts = client.get(f"/api/monthly-packages/{package.id}/ledgers/accounts")

    assert journal.status_code == 200
    assert [row["voucher_number"] for row in journal.json()] == ["记-0001", "记-0001"]
    assert general.status_code == 200
    assert {row["account_code"] for row in general.json()} == {"1002", "5001"}
    assert detail.status_code == 200
    assert detail.json()[0]["balance"] == "200.00"
    assert trial.status_code == 200
    assert trial.json()["is_balanced"] is True
    assert accounts.status_code == 200
    assert accounts.json()[0]["account_code"] == "1002"


def test_historical_ledger_endpoints_return_imported_historical_data():
    client, db_session = make_context()
    package = make_package(db_session)
    add_historical_entry(db_session, package)
    params = {"fiscal_year": 2026, "period_start_month": 1, "period_end_month": 3}

    vouchers = client.get(f"/api/enterprises/{package.enterprise_id}/historical-imports/vouchers", params=params)
    journal = client.get(f"/api/enterprises/{package.enterprise_id}/historical-imports/ledgers/journal", params=params)

    assert vouchers.status_code == 200
    assert vouchers.json()[0]["voucher_number"] == "记-0001"
    assert vouchers.json()[0]["entries"][0]["account_code"] == "5001"
    assert journal.status_code == 200
    assert journal.json()[0]["source_type"] == "历史账套"

    amount_search = client.get(
        f"/api/enterprises/{package.enterprise_id}/historical-imports/vouchers",
        params={**params, "keyword": "100.00"},
    )
    direction_search = client.get(
        f"/api/enterprises/{package.enterprise_id}/historical-imports/vouchers",
        params={**params, "keyword": "贷方"},
    )

    assert amount_search.status_code == 200
    assert amount_search.json()[0]["voucher_number"] == "记-0001"
    assert direction_search.status_code == 200
    assert direction_search.json()[0]["voucher_number"] == "记-0001"
