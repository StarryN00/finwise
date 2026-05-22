from decimal import Decimal

from app.reports.monthly_brief import render_monthly_brief_html
from app.services.enterprise_service import create_enterprise, create_monthly_work_package, save_initial_snapshot
from app.services.import_service import import_bank_rows, import_invoice_rows
from app.services.matching_service import run_matching
from app.services.statement_service import generate_monthly_statement
from app.services.tax_service import generate_tax_filing_draft


def test_end_to_end_monthly_bookkeeping_flow(db_session):
    enterprise = create_enterprise(
        db_session,
        name="苏州端到端测试有限公司",
        unified_social_credit_code="91320500E2E000001",
        taxpayer_type="GENERAL",
        industry="制造业",
    )
    snapshot = save_initial_snapshot(
        db_session,
        enterprise_id=enterprise.id,
        balance_sheet_data={"资产总计": "1000000", "负债合计": "400000", "所有者权益合计": "600000"},
        income_statement_data={"营业收入": "300000", "净利润": "50000"},
    )
    package = create_monthly_work_package(db_session, enterprise_id=enterprise.id, year=2026, month=5)

    bank_result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[
            {
                "交易日期": "2026-05-12",
                "摘要": "收到货款",
                "借方金额": "0",
                "贷方金额": "113000",
                "余额": "113000",
                "对方户名": "苏州客户有限公司",
            }
        ],
    )
    invoice_result = import_invoice_rows(
        db_session,
        monthly_work_package_id=package.id,
        direction="OUTPUT",
        rows=[
            {
                "发票号码": "OUT-E2E-001",
                "开票日期": "2026-05-10",
                "金额": "100000",
                "税额": "13000",
                "价税合计": "113000",
                "购买方名称": "苏州客户有限公司",
            }
        ],
    )

    matching_result = run_matching(db_session, monthly_work_package_id=package.id)
    statement = generate_monthly_statement(db_session, monthly_work_package_id=package.id)
    tax_draft = generate_tax_filing_draft(db_session, monthly_work_package_id=package.id)
    brief_html = render_monthly_brief_html(
        enterprise_name=enterprise.name,
        period="2026-05",
        summary={
            "revenue": statement.estimated_income_statement["revenue"],
            "expense": statement.estimated_income_statement["expense"],
            "cash_net": statement.estimated_balance_sheet["cash_net_movement"],
            "tax_payable": tax_draft.data["vat_payable"],
        },
        exceptions=[],
    )

    assert snapshot.validation_result["balanced"] is True
    assert bank_result["created"] == 1
    assert invoice_result["created"] == 1
    assert matching_result["exact_matches"] == 1
    assert Decimal(str(tax_draft.data["vat_payable"])) == Decimal("13000.00")
    assert "本月经营概览" in brief_html
    assert "现金流提醒" in brief_html
    assert "下月建议" in brief_html
