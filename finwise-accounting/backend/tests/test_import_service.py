from decimal import Decimal
from uuid import UUID

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_db
from app.api.imports import _read_import_frame
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


def test_import_bank_rows_accepts_real_accounting_statement_columns(db_session):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[
            {
                "会计日期": 20260313,
                "摘要": "缴税626031311716014148",
                "借方发生额（支出）": "150.00",
                "贷方发生额（收入）": "0.00",
                "账户余额": "818346.89",
                "对方户名": "银行",
            }
        ],
    )

    transaction = db_session.query(BankTransaction).one()
    assert result["created"] == 1
    assert result["errors"] == []
    assert transaction.transaction_date.isoformat() == "2026-03-13"
    assert transaction.debit_amount == 150


def test_import_bank_rows_accepts_simple_debit_credit_columns(db_session):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[
            {
                "交易日期": "2026-04-08",
                "借方": "200.00",
                "贷方": "",
                "账户余额": "9800.00",
                "对方户名": "苏州供应商",
                "对方账号": "62220001",
                "用途/附言": "采购付款",
            }
        ],
    )

    transaction = db_session.query(BankTransaction).one()
    assert result["created"] == 1
    assert result["errors"] == []
    assert transaction.debit_amount == 200
    assert transaction.credit_amount == 0
    assert transaction.summary == "采购付款"
    assert transaction.counterparty_name == "苏州供应商"


def test_import_bank_rows_accepts_transfer_in_out_columns(db_session):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[
            {
                "入账日期": "2026-02-18",
                "转出金额": "",
                "转入金额": "5000.00",
                "余额": "15000.00",
                "对方单位": "昆山客户",
                "对方账号": "62220002",
                "附言": "服务费回款",
            }
        ],
    )

    transaction = db_session.query(BankTransaction).one()
    assert result["created"] == 1
    assert result["errors"] == []
    assert transaction.transaction_date.isoformat() == "2026-02-18"
    assert transaction.debit_amount == 0
    assert transaction.credit_amount == 5000
    assert transaction.summary == "服务费回款"
    assert transaction.counterparty_name == "昆山客户"


def test_import_bank_rows_classifies_single_amount_by_counterparty_names(db_session):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[
            {
                "交易日期[TransactionDate]": "2026-04-22",
                "交易金额[TradeAmount]": "6600.00",
                "交易后余额[After-transactionbalance]": "26600.00",
                "付款人名称[Payer'sName]": "苏州测试企业",
                "收款人名称[Payee'sName]": "苏州供应商",
                "摘要[Reference]": "货款",
            },
            {
                "交易日期[TransactionDate]": "2026-04-23",
                "交易金额[TradeAmount]": "8800.00",
                "交易后余额[After-transactionbalance]": "35400.00",
                "付款人名称[Payer'sName]": "苏州客户",
                "收款人名称[Payee'sName]": "苏州测试企业",
                "摘要[Reference]": "回款",
            },
        ],
    )

    transactions = db_session.query(BankTransaction).order_by(BankTransaction.transaction_date).all()
    assert result["created"] == 2
    assert result["errors"] == []
    assert transactions[0].debit_amount == 6600
    assert transactions[0].credit_amount == 0
    assert transactions[1].debit_amount == 0
    assert transactions[1].credit_amount == 8800


def test_import_bank_rows_skips_bank_summary_rows(db_session):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[
            {"会计日期": "20260401", "摘要": "收款", "贷方发生额（收入）": "1000.00"},
            {"会计日期": "", "摘要": "贷方交易笔数", "贷方发生额（收入）": "贷方交易笔数"},
        ],
    )

    transaction = db_session.query(BankTransaction).one()
    assert result["created"] == 1
    assert result["errors"] == []
    assert transaction.credit_amount == 1000


def test_import_frame_detects_late_bank_header_and_multiple_sheets(tmp_path):
    path = tmp_path / "multi-sheet-bank.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"空": []}).to_excel(writer, sheet_name="空表", index=False)
        rows = [["说明", "", "", ""], ["账号", "", "", ""]]
        rows.extend([["", "", "", ""] for _ in range(13)])
        rows.append(["交易日", "借方金额（出）", "贷方金额（进）", "摘要"])
        rows.append(["2026-04-01", "100.00", "", "付款"])
        pd.DataFrame(rows).to_excel(writer, sheet_name="4月", header=False, index=False)

    frame = _read_import_frame(str(path), ".xlsx")

    assert list(frame.columns)[:4] == ["交易日", "借方金额（出）", "贷方金额（进）", "摘要"]
    assert frame.iloc[0]["摘要"] == "付款"


def test_import_frame_detects_general_taxpayer_invoice_checklist(tmp_path):
    path = tmp_path / "general-taxpayer-input-invoices.xlsx"
    rows = [
        ["发票清单", "发票清单", "发票清单", "发票清单", "发票清单", "发票清单", "发票清单", "发票清单"],
        ["纳税人识别号", "91320583TEST", "", "税款所属期", "202604", "", "纳税人名称", "苏州测试企业"],
        ["序号", "勾选状态", "数电发票号码", "发票代码", "发票号码", "开票日期", "销售方名称", "金额", "税额", "有效抵扣税额"],
        [1, "已勾选", "26312000002191099006", "263120000021", "91099006", "2026-04-10 13:09:39", "上海供应商", "25663.72", "3336.28", "3336.28"],
        ["合计", "", "", "", "", "", "", "25663.72", "3336.28", "3336.28"],
    ]
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="发票", header=False, index=False)

    frame = _read_import_frame(str(path), ".xlsx")

    assert list(frame.columns)[:6] == ["序号", "勾选状态", "数电发票号码", "发票代码", "发票号码", "开票日期"]
    assert len(frame) == 1
    assert frame.iloc[0]["销售方名称"] == "上海供应商"


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


def test_import_invoice_rows_accepts_general_taxpayer_input_without_total_amount(db_session):
    package = make_package(db_session)

    result = import_invoice_rows(
        db_session,
        monthly_work_package_id=package.id,
        direction="INPUT",
        rows=[
            {
                "数电发票号码": "26312000002191099006",
                "发票号码": "91099006",
                "开票日期": "2026-04-10 13:09:39",
                "销售方名称": "上海供应商",
                "金额": "25663.72",
                "税额": "3336.28",
                "有效抵扣税额": "3336.28",
            }
        ],
    )

    invoice = db_session.query(Invoice).one()
    assert result["created"] == 1
    assert result["errors"] == []
    assert invoice.invoice_direction == "INPUT"
    assert invoice.invoice_number == "26312000002191099006"
    assert invoice.invoice_date.isoformat() == "2026-04-10"
    assert invoice.amount == Decimal("25663.72")
    assert invoice.tax_amount == Decimal("3336.28")
    assert invoice.total_amount == Decimal("29000.00")
    assert invoice.seller_name == "上海供应商"


def test_import_invoice_rows_skips_general_taxpayer_invoice_summary_row(db_session):
    package = make_package(db_session)

    result = import_invoice_rows(
        db_session,
        monthly_work_package_id=package.id,
        direction="INPUT",
        rows=[
            {
                "序号": "合计",
                "金额": "25663.72",
                "税额": "3336.28",
                "有效抵扣税额": "3336.28",
            }
        ],
    )

    assert result["created"] == 0
    assert result["errors"] == []
    assert db_session.query(Invoice).count() == 0


def test_import_invoice_rows_accepts_digital_invoice_number(db_session):
    package = make_package(db_session)

    result = import_invoice_rows(
        db_session,
        monthly_work_package_id=package.id,
        direction="OUTPUT",
        rows=[
            {
                "数电发票号码": "26322000002259829066",
                "开票日期": "2026-03-24 17:23:49",
                "金额": "71681.42",
                "税额": "9318.58",
                "价税合计": "81000.00",
            }
        ],
    )

    invoice = db_session.query(Invoice).one()
    assert result["created"] == 1
    assert result["errors"] == []
    assert invoice.invoice_number == "26322000002259829066"


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


def test_import_bank_rows_accepts_explicit_single_digit_separator_date(db_session):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[{"交易日期": "2026.5.8", "摘要": "收到货款", "贷方金额": "11300.00"}],
    )

    transaction = db_session.query(BankTransaction).one()
    assert result["created"] == 1
    assert result["errors"] == []
    assert transaction.transaction_date.isoformat() == "2026-05-08"


def test_import_bank_rows_rejects_ambiguous_slash_date(db_session):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[{"交易日期": "05/06/2026", "摘要": "收到货款", "贷方金额": "11300.00"}],
    )

    assert result["created"] == 0
    assert result["errors"][0]["row"] == 1
    assert db_session.query(BankTransaction).count() == 0


def test_import_bank_rows_accepts_numeric_yyyymmdd_dates(db_session):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[{"交易日期": 20260508, "摘要": "收到货款", "贷方金额": "11300.00"}],
    )

    transaction = db_session.query(BankTransaction).one()
    assert result["created"] == 1
    assert result["errors"] == []
    assert transaction.transaction_date.isoformat() == "2026-05-08"


def test_import_bank_rows_rejects_excel_serial_numeric_dates(db_session):
    package = make_package(db_session)

    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[{"交易日期": 45000, "摘要": "收到货款", "贷方金额": "11300.00"}],
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


def test_gb18030_csv_upload_imports_bank_rows(db_session):
    package = make_package(db_session)
    app = create_app(init_db_on_startup=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    csv_content = "交易日期,摘要,贷方金额\n2026-05-08,收到货款,11300.00\n".encode("gb18030")

    response = client.post(
        f"/api/monthly-packages/{package.id}/imports/bank",
        files={"file": ("bank.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 200
    assert response.json()["created"] == 1
