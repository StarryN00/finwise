from uuid import UUID

import pytest

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


def test_import_invoice_rows_missing_package_raises_domain_error(db_session):
    with pytest.raises(MonthlyPackageNotFoundError, match="Monthly work package not found"):
        import_invoice_rows(
            db_session,
            monthly_work_package_id=UUID("00000000-0000-0000-0000-000000000099"),
            direction="INPUT",
            rows=[],
        )
