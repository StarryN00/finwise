from uuid import UUID

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.main import create_app
from app.models import BankTransaction, Enterprise, Invoice, MonthlyWorkPackage
from app.services.import_service import MonthlyPackageNotFoundError, import_bank_rows, import_invoice_rows


def make_package(db_session):
    enterprise = Enterprise(
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        name="苏州测试企业",
        unified_social_credit_code="91320500TESTIMPORT01",
        taxpayer_type="GENERAL",
        industry="制造业",
    )
    db_session.add(enterprise)
    db_session.flush()

    package = MonthlyWorkPackage(
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
    )
    db_session.add(package)
    db_session.commit()
    return package


def test_import_bank_rows_maps_common_columns(db_session):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[{"交易日期": "2026-05-08", "摘要": "收到货款", "贷方金额": "11300.00", "对方户名": "苏州客户"}],
    )

    transaction = db_session.query(BankTransaction).one()
    assert result["created"] == 1
    assert result["errors"] == []
    assert transaction.raw_row_data["摘要"] == "收到货款"


def test_import_invoice_rows_maps_input_and_output(db_session):
    package = make_package(db_session)

    result = import_invoice_rows(
        db_session,
        monthly_work_package_id=package.id,
        direction="OUTPUT",
        rows=[{"发票号码": "0001", "开票日期": "2026/05/06", "金额": "10000", "税额": "1300", "价税合计": "11300"}],
    )

    invoice = db_session.query(Invoice).one()
    assert result["created"] == 1
    assert result["errors"] == []
    assert invoice.invoice_direction == "OUTPUT"


def test_import_bank_rows_reports_invalid_date_without_crashing(db_session):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[{"交易日期": "not-a-date", "摘要": "收到货款", "贷方金额": "11300.00"}],
    )

    assert result["created"] == 0
    assert result["errors"][0]["row"] == 1
    assert db_session.query(BankTransaction).count() == 0


def test_import_bank_rows_reports_nat_date_without_crashing(db_session):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[{"交易日期": pd.NaT, "摘要": "收到货款", "贷方金额": "11300.00"}],
    )

    assert result["created"] == 0
    assert result["errors"][0]["row"] == 1
    assert db_session.query(BankTransaction).count() == 0


def test_import_bank_rows_accepts_yyyymmdd_string_date(db_session):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[{"交易日期": "20260508", "摘要": "收到货款", "贷方金额": "11300.00"}],
    )

    transaction = db_session.query(BankTransaction).one()
    assert result["created"] == 1
    assert result["errors"] == []
    assert transaction.transaction_date.isoformat() == "2026-05-08"


@pytest.mark.parametrize("date_value", [20260508, 45000])
def test_import_bank_rows_rejects_numeric_dates(db_session, date_value):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[{"交易日期": date_value, "摘要": "收到货款", "贷方金额": "11300.00"}],
    )

    assert result["created"] == 0
    assert result["errors"][0]["row"] == 1
    assert db_session.query(BankTransaction).count() == 0


def test_import_invoice_rows_reports_nan_amount_without_crashing(db_session):
    package = make_package(db_session)

    result = import_invoice_rows(
        db_session,
        monthly_work_package_id=package.id,
        direction="INPUT",
        rows=[{"发票号码": "0002", "开票日期": "2026-05-07", "金额": float("nan"), "税额": "1300", "价税合计": "11300"}],
    )

    assert result["created"] == 0
    assert result["errors"][0]["row"] == 1
    assert db_session.query(Invoice).count() == 0


def test_import_invoice_rows_reports_missing_amount_without_creating_invoice(db_session):
    package = make_package(db_session)

    result = import_invoice_rows(
        db_session,
        monthly_work_package_id=package.id,
        direction="INPUT",
        rows=[{"发票号码": "0003", "开票日期": "2026-05-07", "税额": "1300", "价税合计": "11300"}],
    )

    assert result["created"] == 0
    assert result["errors"][0]["row"] == 1
    assert db_session.query(Invoice).count() == 0


@pytest.mark.parametrize("invoice_number", [None, "", float("nan")])
def test_import_invoice_rows_requires_invoice_number(db_session, invoice_number):
    package = make_package(db_session)

    result = import_invoice_rows(
        db_session,
        monthly_work_package_id=package.id,
        direction="INPUT",
        rows=[
            {
                "发票号码": invoice_number,
                "开票日期": "2026-05-07",
                "金额": "10000",
                "税额": "1300",
                "价税合计": "11300",
            }
        ],
    )

    assert result["created"] == 0
    assert result["errors"][0]["row"] == 1
    assert db_session.query(Invoice).count() == 0


def test_import_invoice_rows_missing_package_raises_domain_error(db_session):
    with pytest.raises(MonthlyPackageNotFoundError, match="Monthly work package not found"):
        import_invoice_rows(
            db_session,
            monthly_work_package_id=UUID("00000000-0000-0000-0000-000000000099"),
            direction="INPUT",
            rows=[],
        )


def test_import_bank_rows_rolls_back_commit_failures(db_session, monkeypatch):
    package = make_package(db_session)

    def fail_commit():
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(db_session, "commit", fail_commit)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[{"交易日期": "2026-05-08", "摘要": "收到货款", "贷方金额": "11300.00"}],
    )

    assert result["created"] == 0
    assert result["batch_errors"][0]["error"] == "database unavailable"


def test_malformed_excel_upload_returns_400():
    client = TestClient(create_app(init_db_on_startup=False), raise_server_exceptions=False)

    response = client.post(
        "/api/monthly-packages/00000000-0000-0000-0000-000000000001/imports/bank",
        files={
            "file": (
                "broken.xlsx",
                b"not an excel file",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 400
    assert "Could not read import file" in response.json()["detail"]
