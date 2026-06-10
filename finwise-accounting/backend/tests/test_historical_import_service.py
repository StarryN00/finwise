from uuid import UUID

import pandas as pd
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.historical_imports import read_historical_balance_rows, read_historical_ledger_rows
from app.main import create_app
from app.models import Enterprise, HistoricalBalanceRow, HistoricalImportBatch, HistoricalLedgerEntry
from app.services.historical_import_service import HistoricalImportError, import_historical_books


def make_enterprise(db_session):
    enterprise = Enterprise(
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        name="昆山黛珂特电子科技有限公司",
        unified_social_credit_code="91320500HISTORY001",
        taxpayer_type="GENERAL",
        industry="电子制造",
    )
    db_session.add(enterprise)
    db_session.commit()
    return enterprise


def test_read_historical_ledger_rows_detects_gbt24589_export_header(tmp_path):
    path = tmp_path / "ledger.xlsx"
    rows = [
        ["序时账", None, None, None],
        ["2025年01月至2025年12月", None, None, None],
        ["日期", "凭证字号", "摘要", "科目全称", "科目编码", "科目名称", "借方金额", "贷方金额"],
        ["2025-01-13", "记-008", "销售收入", "主营业务收入", "5001", "主营业务收入", None, "235918.28"],
    ]
    pd.DataFrame(rows).to_excel(path, sheet_name="序时账_2025年01月至2025年12月", header=False, index=False)

    parsed = read_historical_ledger_rows(path)

    assert parsed[0]["date"] == "2025-01-13"
    assert parsed[0]["voucher_no"] == "记-008"
    assert parsed[0]["account_code"] == "5001"
    assert parsed[0]["credit_amount"] == "235918.28"


def test_read_historical_balance_rows_detects_two_level_amount_headers(tmp_path):
    path = tmp_path / "balance.xlsx"
    rows = [
        ["科目余额表", None, None, None, None, None, None, None],
        ["编制单位：昆山黛珂特电子科技有限公司", None, None, None, None, None, None, None],
        [None, None, None, "2025年01月至2025年12月", None, None, "单位：元", None],
        ["科目编码", "科目名称", "期初余额", None, "本期发生额", None, "期末余额", None],
        [None, None, "借方", "贷方", "借方", "贷方", "借方", "贷方"],
        ["1002", "银行存款", "460918.98", None, "41807588.52", "42215816.33", "52691.17", None],
    ]
    pd.DataFrame(rows).to_excel(path, sheet_name="余额表_2025年01月至2025年12月", header=False, index=False)

    parsed = read_historical_balance_rows(path)

    assert parsed[0]["account_code"] == "1002"
    assert parsed[0]["account_name"] == "银行存款"
    assert parsed[0]["opening_debit"] == "460918.98"
    assert parsed[0]["period_credit"] == "42215816.33"
    assert parsed[0]["closing_debit"] == "52691.17"


def test_import_historical_books_replaces_same_year_rows_after_valid_import(db_session):
    enterprise = make_enterprise(db_session)

    first = import_historical_books(
        db_session,
        enterprise_id=enterprise.id,
        fiscal_year=2025,
        ledger_rows=[
            {
                "date": "2025-01-13",
                "voucher_no": "记-008",
                "summary": "销售收入",
                "account_full_name": "主营业务收入",
                "account_code": "5001",
                "account_name": "主营业务收入",
                "debit_amount": "",
                "credit_amount": "235918.28",
            }
        ],
        balance_rows=[
            {
                "account_code": "1002",
                "account_name": "银行存款",
                "opening_debit": "460918.98",
                "opening_credit": "",
                "period_debit": "41807588.52",
                "period_credit": "42215816.33",
                "closing_debit": "52691.17",
                "closing_credit": "",
            }
        ],
        ledger_filename="序时账.xls",
        balance_filename="余额表.xls",
    )
    second = import_historical_books(
        db_session,
        enterprise_id=enterprise.id,
        fiscal_year=2025,
        ledger_rows=[
            {
                "date": "2025-02-01",
                "voucher_no": "记-009",
                "summary": "采购",
                "account_full_name": "原材料",
                "account_code": "1403",
                "account_name": "原材料",
                "debit_amount": "100.00",
                "credit_amount": "",
            }
        ],
        balance_rows=[],
        ledger_filename="second-ledger.xls",
        balance_filename="second-balance.xls",
    )

    assert first.created_ledger_rows == 1
    assert first.created_balance_rows == 1
    assert first.status == "IMPORTED"
    assert second.replaced_ledger_rows == 1
    assert second.replaced_balance_rows == 1
    assert db_session.query(HistoricalLedgerEntry).count() == 1
    assert db_session.query(HistoricalBalanceRow).count() == 0
    assert db_session.query(HistoricalImportBatch).count() == 2


def test_failed_historical_import_preserves_existing_same_year_rows(db_session):
    enterprise = make_enterprise(db_session)
    import_historical_books(
        db_session,
        enterprise_id=enterprise.id,
        fiscal_year=2025,
        ledger_rows=[
            {
                "date": "2025-01-13",
                "voucher_no": "记-008",
                "summary": "销售收入",
                "account_full_name": "主营业务收入",
                "account_code": "5001",
                "account_name": "主营业务收入",
                "debit_amount": "",
                "credit_amount": "235918.28",
            }
        ],
        balance_rows=[],
        ledger_filename="序时账.xls",
        balance_filename="余额表.xls",
    )

    failed = import_historical_books(
        db_session,
        enterprise_id=enterprise.id,
        fiscal_year=2025,
        ledger_rows=[{"date": "bad-date", "voucher_no": "", "account_code": "", "account_name": ""}],
        balance_rows=[],
        ledger_filename="bad-ledger.xls",
        balance_filename="bad-balance.xls",
    )

    assert failed.status == "FAILED"
    assert failed.replaced_ledger_rows == 0
    assert db_session.query(HistoricalLedgerEntry).count() == 1


def test_historical_import_rejects_wrong_enterprise_metadata(db_session):
    enterprise = make_enterprise(db_session)

    try:
        import_historical_books(
            db_session,
            enterprise_id=enterprise.id,
            fiscal_year=2025,
            ledger_rows=[],
            balance_rows=[],
            ledger_filename="序时账.xls",
            balance_filename="余额表.xls",
            source_metadata={"balance_company_name": "昆山其他企业有限公司", "balance_period_text": "2025年01月至2025年12月"},
        )
    except HistoricalImportError as exc:
        assert "selected enterprise" in str(exc)
    else:
        raise AssertionError("expected enterprise metadata mismatch to be rejected")


def test_historical_import_rejects_wrong_fiscal_year_metadata(db_session):
    enterprise = make_enterprise(db_session)

    try:
        import_historical_books(
            db_session,
            enterprise_id=enterprise.id,
            fiscal_year=2025,
            ledger_rows=[],
            balance_rows=[],
            ledger_filename="序时账.xls",
            balance_filename="余额表.xls",
            source_metadata={"ledger_period_text": "2024年01月至2024年12月"},
        )
    except HistoricalImportError as exc:
        assert "selected fiscal year" in str(exc)
    else:
        raise AssertionError("expected fiscal year metadata mismatch to be rejected")


def test_historical_import_accepts_selected_partial_accounting_period(db_session):
    enterprise = make_enterprise(db_session)

    result = import_historical_books(
        db_session,
        enterprise_id=enterprise.id,
        fiscal_year=2026,
        period_start_month=1,
        period_end_month=3,
        ledger_rows=[
            {
                "date": "2026-03-31",
                "voucher_no": "记-001",
                "summary": "季度测试",
                "account_full_name": "银行存款",
                "account_code": "1002",
                "account_name": "银行存款",
                "debit_amount": "100.00",
                "credit_amount": "",
            }
        ],
        balance_rows=[],
        ledger_filename="序时账.xls",
        balance_filename="余额表.xls",
        source_metadata={"ledger_period_text": "2026年01月至2026年03月"},
    )

    assert result.fiscal_year == 2026
    assert result.period_start_month == 1
    assert result.period_end_month == 3
    entry = db_session.query(HistoricalLedgerEntry).one()
    assert entry.period_start_month == 1
    assert entry.period_end_month == 3


def test_historical_import_rejects_wrong_accounting_period_metadata(db_session):
    enterprise = make_enterprise(db_session)

    try:
        import_historical_books(
            db_session,
            enterprise_id=enterprise.id,
            fiscal_year=2026,
            period_start_month=1,
            period_end_month=3,
            ledger_rows=[],
            balance_rows=[],
            ledger_filename="序时账.xls",
            balance_filename="余额表.xls",
            source_metadata={"ledger_period_text": "2026年01月至2026年12月"},
        )
    except HistoricalImportError as exc:
        assert "selected accounting period" in str(exc)
    else:
        raise AssertionError("expected accounting period metadata mismatch to be rejected")


def test_historical_import_rejects_ledger_rows_outside_selected_period(db_session):
    enterprise = make_enterprise(db_session)

    result = import_historical_books(
        db_session,
        enterprise_id=enterprise.id,
        fiscal_year=2026,
        period_start_month=1,
        period_end_month=3,
        ledger_rows=[
            {
                "date": "2026-04-01",
                "voucher_no": "记-001",
                "summary": "期间外",
                "account_full_name": "银行存款",
                "account_code": "1002",
                "account_name": "银行存款",
                "debit_amount": "100.00",
                "credit_amount": "",
            }
        ],
        balance_rows=[],
        ledger_filename="序时账.xls",
        balance_filename="余额表.xls",
    )

    assert result.status == "FAILED"
    assert result.validation_summary["ledger_error_count"] == 1
    assert db_session.query(HistoricalLedgerEntry).count() == 0


def test_historical_import_preserves_endpoint_auxiliary_dimensions(db_session):
    enterprise = make_enterprise(db_session)

    import_historical_books(
        db_session,
        enterprise_id=enterprise.id,
        fiscal_year=2025,
        ledger_rows=[
            {
                "date": "2025-01-13",
                "voucher_no": "记-008",
                "summary": "销售收入",
                "account_full_name": "应收账款_客户A",
                "account_code": "1122001",
                "account_name": "客户A",
                "debit_amount": "100.00",
                "credit_amount": "",
                "customer_code": "C001",
                "customer_name": "客户A",
            }
        ],
        balance_rows=[],
        ledger_filename="序时账.xls",
        balance_filename="余额表.xls",
    )

    entry = db_session.query(HistoricalLedgerEntry).one()
    assert entry.auxiliary["customer_code"] == "C001"
    assert entry.auxiliary["customer_name"] == "客户A"


def test_historical_import_counts_all_unbalanced_vouchers_while_sampling_ten(db_session):
    enterprise = make_enterprise(db_session)
    ledger_rows = []
    for number in range(12):
        ledger_rows.append(
            {
                "date": "2025-01-13",
                "voucher_no": f"记-{number:03d}",
                "summary": "不平测试",
                "account_full_name": "主营业务收入",
                "account_code": "5001",
                "account_name": "主营业务收入",
                "debit_amount": "1.00",
                "credit_amount": "",
            }
        )

    result = import_historical_books(
        db_session,
        enterprise_id=enterprise.id,
        fiscal_year=2025,
        ledger_rows=ledger_rows,
        balance_rows=[],
        ledger_filename="序时账.xls",
        balance_filename="余额表.xls",
    )

    assert result.validation_summary["unbalanced_voucher_count"] == 12
    assert len(result.validation_summary["unbalanced_voucher_samples"]) == 10


def test_historical_import_endpoint_accepts_two_files(db_session, tmp_path):
    enterprise = make_enterprise(db_session)
    ledger_path = tmp_path / "ledger.xlsx"
    balance_path = tmp_path / "balance.xlsx"
    pd.DataFrame(
        [
            ["序时账", None, None, None],
            ["2025年01月至2025年12月", None, None, None],
            ["日期", "凭证字号", "摘要", "科目全称", "科目编码", "科目名称", "借方金额", "贷方金额"],
            ["2025-01-13", "记-008", "销售收入", "主营业务收入", "5001", "主营业务收入", None, "235918.28"],
        ]
    ).to_excel(ledger_path, header=False, index=False)
    pd.DataFrame(
        [
            ["科目余额表", None, None, None, None, None, None, None],
            ["编制单位：昆山黛珂特电子科技有限公司", None, None, None, None, None, None, None],
            [None, None, None, "2025年01月至2025年12月", None, None, "单位：元", None],
            ["科目编码", "科目名称", "期初余额", None, "本期发生额", None, "期末余额", None],
            [None, None, "借方", "贷方", "借方", "贷方", "借方", "贷方"],
            ["1002", "银行存款", "460918.98", None, "41807588.52", "42215816.33", "52691.17", None],
        ]
    ).to_excel(balance_path, header=False, index=False)
    app = create_app(init_db_on_startup=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    with ledger_path.open("rb") as ledger_file, balance_path.open("rb") as balance_file:
        response = client.post(
            f"/api/enterprises/{enterprise.id}/historical-imports/gbt24589",
            data={"fiscal_year": "2025", "period_start_month": "1", "period_end_month": "12"},
            files={
                "ledger_file": ("ledger.xlsx", ledger_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "balance_file": ("balance.xlsx", balance_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    assert response.status_code == 201
    assert response.json()["created_ledger_rows"] == 1
    assert response.json()["created_balance_rows"] == 1
    assert response.json()["period_start_month"] == 1
    assert response.json()["period_end_month"] == 12


def test_historical_import_endpoint_lists_enterprise_import_records(db_session):
    enterprise = make_enterprise(db_session)
    import_historical_books(
        db_session,
        enterprise_id=enterprise.id,
        fiscal_year=2025,
        ledger_rows=[
            {
                "date": "2025-01-13",
                "voucher_no": "记-008",
                "summary": "销售收入",
                "account_full_name": "主营业务收入",
                "account_code": "5001",
                "account_name": "主营业务收入",
                "debit_amount": "",
                "credit_amount": "235918.28",
            }
        ],
        balance_rows=[],
        ledger_filename="序时账_2025.xls",
        balance_filename="余额表_2025.xls",
    )
    app = create_app(init_db_on_startup=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.get(f"/api/enterprises/{enterprise.id}/historical-imports")

    assert response.status_code == 200
    records = response.json()
    assert len(records) == 1
    assert records[0]["fiscal_year"] == 2025
    assert records[0]["ledger_filename"] == "序时账_2025.xls"
    assert records[0]["created_ledger_rows"] == 1
