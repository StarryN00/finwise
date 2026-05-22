from datetime import date
from decimal import Decimal
from uuid import UUID

from app.models import Enterprise, MonthlyStatement, MonthlyWorkPackage, TaxFilingDraft
from app.reports.health_diagnosis import build_health_diagnosis
from app.reports.monthly_brief import render_monthly_brief_html
from app.services.report_service import desensitize_ai_payload, generate_health_report


ORG = UUID("00000000-0000-0000-0000-000000000001")


def make_package(db_session):
    enterprise = Enterprise(
        organization_id=ORG,
        name="苏州样例科技有限公司",
        unified_social_credit_code="91320500REPORT000001",
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


def test_monthly_brief_contains_owner_facing_sections():
    html = render_monthly_brief_html(
        enterprise_name="苏州样例科技有限公司",
        period="2026-05",
        summary={"revenue": 100000, "expense": 60000, "cash_net": 20000, "tax_payable": 7800},
        exceptions=[{"label": "未匹配流水", "count": 2}],
    )

    assert "本月经营概览" in html
    assert "税务概览" in html
    assert "现金流提醒" in html
    assert "下月建议" in html


def test_health_diagnosis_returns_data_insufficient_with_missing_messages():
    result = build_health_diagnosis(
        enterprise={"name": "苏州样例科技有限公司", "industry": "制造业"},
        period="2026-05",
        statement={},
        tax_draft={},
    )

    assert result["status"] == "DATA_INSUFFICIENT"
    assert "缺少资产负债表核心数据" in result["missing_data"]
    assert "缺少利润表核心数据" in result["missing_data"]


def test_ai_payload_masks_sensitive_names_and_tax_numbers():
    payload = desensitize_ai_payload(
        {
            "enterprise_name": "苏州样例科技有限公司",
            "tax_number": "91320500INIT000001",
            "counterparty_name": "苏州重要客户有限公司",
            "summary": "收到苏州重要客户货款",
            "amount": "11300.00",
            "direction": "INCOME",
            "date_distance": 2,
        }
    )

    assert "苏州样例科技有限公司" not in str(payload)
    assert "91320500INIT000001" not in str(payload)
    assert "苏州重要客户" not in str(payload)
    assert payload["counterparty_name"] == "苏州***公司"
    assert payload["amount"] == "11300.00"
    assert payload["direction"] == "INCOME"
    assert payload["date_distance"] == 2


def test_generate_health_report_persists_html_snapshot(db_session, tmp_path):
    enterprise, package = make_package(db_session)
    db_session.add(
        MonthlyStatement(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            estimated_balance_sheet={
                "total_assets": "48000000.00",
                "total_liabilities": "26000000.00",
                "cash_net_movement": "200000.00",
            },
            estimated_income_statement={
                "revenue": "1200000.00",
                "cost": "760000.00",
                "expense": "120000.00",
                "operating_profit": "320000.00",
            },
        )
    )
    db_session.add(
        TaxFilingDraft(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            data={"vat_payable": "7800.00", "surcharge_estimate": "936.00"},
            status="DRAFT",
        )
    )
    db_session.commit()

    report = generate_health_report(db_session, monthly_work_package_id=package.id, output_dir=tmp_path)

    assert report.status == "READY"
    assert report.report_type == "FINANCIAL_HEALTH"
    assert report.html_path is not None
    html = tmp_path.joinpath(f"health-report-{package.id}.html").read_text(encoding="utf-8")
    assert enterprise.name in html
    assert "执行摘要与关键结论" in html
    assert "税务风险" in html
