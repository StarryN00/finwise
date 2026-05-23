from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.api.deps import get_db
from app.main import create_app
from app.models import Enterprise, InitialFinancialSnapshot, MonthlyStatement, MonthlyWorkPackage, TaxFilingDraft
from app.reports.health_diagnosis import build_health_diagnosis
from app.reports.monthly_brief import render_monthly_brief_html
from app.services.report_service import build_health_report_ai_payload, desensitize_ai_payload, generate_health_report


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


def test_generate_health_report_uses_ai_client_with_desensitized_payload(db_session, tmp_path):
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
    seen_payloads = []

    class FakeHealthAiClient:
        def generate_report(self, payload):
            seen_payloads.append(payload)
            return {
                "sections": [
                    {"title": "一、执行摘要与关键结论", "content": ["AI 判断现金流质量稳定，短期税负可控。"]},
                    {"title": "二、风险等级总览矩阵", "content": ["偿债能力：低风险；盈利能力：中风险；税务风险：低风险。"]},
                    {"title": "三、经营建议", "content": ["继续跟踪回款周期，建立月度发票与流水匹配复核。"]},
                ]
            }

    report = generate_health_report(
        db_session,
        monthly_work_package_id=package.id,
        output_dir=tmp_path,
        ai_client=FakeHealthAiClient(),
    )

    html = tmp_path.joinpath(f"health-report-{package.id}.html").read_text(encoding="utf-8")
    assert report.status == "READY"
    assert report.data_version["source"] == "ai_health_report"
    assert "AI 判断现金流质量稳定" in html
    assert "风险等级总览矩阵" in html
    assert seen_payloads
    assert enterprise.name not in str(seen_payloads[0])
    assert enterprise.unified_social_credit_code not in str(seen_payloads[0])
    assert seen_payloads[0]["enterprise_profile"]["name"] == "本企业"


def test_generate_health_report_uses_initial_snapshot_when_statement_lacks_core_balance_data(db_session, tmp_path):
    enterprise, package = make_package(db_session)
    db_session.add(
        InitialFinancialSnapshot(
            organization_id=ORG,
            enterprise_id=enterprise.id,
            balance_sheet_data={
                "资产总计": "908486.12",
                "负债合计": "952699.44",
                "货币资金": "614277.56",
                "应收账款": "39863.80",
                "存货": "82575.21",
            },
            income_statement_data={
                "营业收入": "251415.93",
                "营业成本": "226274.34",
                "管理费用": "10387.26",
                "营业利润": "14754.33",
                "净利润": "14754.33",
            },
        )
    )
    db_session.add(
        MonthlyStatement(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            estimated_balance_sheet={"cash_net_movement": "-64576.00"},
            estimated_income_statement={"revenue": "0.00", "operating_profit": "0.00"},
        )
    )
    db_session.add(
        TaxFilingDraft(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            data={"vat_payable": "0.00", "surcharge_estimate": "0.00"},
            status="DRAFT",
        )
    )
    db_session.commit()

    report = generate_health_report(db_session, monthly_work_package_id=package.id, output_dir=tmp_path)

    html = tmp_path.joinpath(f"health-report-{package.id}.html").read_text(encoding="utf-8")
    assert report.status == "READY"
    assert report.data_version["missing_data"] == []
    assert "资产负债率" in html
    assert "营业利润率" in html


def test_ai_health_report_html_uses_diagnostic_report_layout(db_session, tmp_path):
    enterprise, package = make_package(db_session)
    db_session.add(
        MonthlyStatement(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            estimated_balance_sheet={
                "total_assets": "908486.12",
                "total_liabilities": "952699.44",
                "cash_net_movement": "-64576.00",
            },
            estimated_income_statement={
                "revenue": "251415.93",
                "cost": "226274.34",
                "expense": "10387.26",
                "operating_profit": "14754.33",
            },
        )
    )
    db_session.add(
        TaxFilingDraft(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            data={"vat_payable": "0.00", "surcharge_estimate": "0.00"},
            status="DRAFT",
        )
    )
    db_session.commit()

    class FakeHealthAiClient:
        def generate_report(self, payload):
            return {
                "sections": [
                    {"title": "一、执行摘要与关键结论", "content": ["AI 认为资产负债率偏高，需优先压降短期债务。"]},
                    {"title": "二、风险等级总览矩阵", "content": ["偿债能力：高风险；盈利能力：中风险；税务风险：低风险。"]},
                    {"title": "三、改进建议", "content": ["建立回款计划，并按月复核进销项匹配。"]},
                ]
            }

    report = generate_health_report(
        db_session,
        monthly_work_package_id=package.id,
        output_dir=tmp_path,
        ai_client=FakeHealthAiClient(),
    )

    html = tmp_path.joinpath(f"health-report-{package.id}.html").read_text(encoding="utf-8")
    assert report.status == "READY"
    assert "risk-overview" in html
    assert "metric-grid" in html
    assert "资产负债率" in html
    assert "AI 认为资产负债率偏高" in html


def test_ai_health_report_html_matches_formal_pdf_report_structure(db_session, tmp_path):
    enterprise, package = make_package(db_session)
    db_session.add(
        MonthlyStatement(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            estimated_balance_sheet={
                "total_assets": "908486.12",
                "total_liabilities": "952699.44",
                "cash": "614277.56",
                "accounts_receivable": "39863.80",
                "inventory": "82575.21",
                "accounts_payable": "785700.00",
                "cash_net_movement": "-64576.00",
            },
            estimated_income_statement={
                "revenue": "251415.93",
                "cost": "226274.34",
                "expense": "10387.26",
                "operating_profit": "14754.33",
                "net_profit": "14754.33",
            },
        )
    )
    db_session.add(
        TaxFilingDraft(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            data={
                "output_amount": "251415.93",
                "output_tax": "32684.07",
                "input_amount": "282218.70",
                "input_tax": "36544.80",
                "vat_payable": "0.00",
                "unmatched_invoice_count": 12,
            },
            status="DRAFT",
        )
    )
    db_session.commit()

    class FakeHealthAiClient:
        def generate_report(self, payload):
            return {
                "sections": [
                    {"title": "一、执行摘要与关键结论", "content": ["AI 认为资产负债率偏高，需优先压降短期债务。"]},
                    {"title": "三、偿债能力分析", "content": ["企业资产负债率高于安全线。"]},
                    {"title": "六、税务风险与合规提示", "content": ["未匹配发票需在申报前复核。"]},
                ]
            }

    report = generate_health_report(
        db_session,
        monthly_work_package_id=package.id,
        output_dir=tmp_path,
        ai_client=FakeHealthAiClient(),
    )

    html = tmp_path.joinpath(f"health-report-{package.id}.html").read_text(encoding="utf-8")
    assert report.status == "READY"
    assert "FINANCIAL HEALTH DIAGNOSTIC" in html
    assert "企业财务健康诊断报告" in html
    assert "report-page cover-page" in html
    assert "page-number" in html
    assert "一、执行摘要与关键结论" in html
    assert "二、公司概况" in html
    assert "小微企业资格判定" in html
    assert "三、偿债能力分析" in html
    assert "四、盈利能力分析" in html
    assert "五、运营效率与现金流分析" in html
    assert "六、税务风险与合规提示" in html
    assert "七、风险量化与改进建议" in html
    assert "图 1" in html
    assert "图 2" in html
    assert "图 3" in html
    assert "图 4" in html
    assert "资产负债率</span>" in html
    assert "104.87%</strong>" in html
    assert "利润率</span>" in html
    assert "5.87%</strong>" in html
    assert html.count("report-page") >= 8


def test_generate_health_report_creates_template_based_pdf(db_session, tmp_path):
    enterprise, package = make_package(db_session)
    db_session.add(
        MonthlyStatement(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            estimated_balance_sheet={
                "total_assets": "908486.12",
                "total_liabilities": "952699.44",
                "cash": "614277.56",
                "accounts_receivable": "39863.80",
                "inventory": "82575.21",
                "accounts_payable": "785700.00",
                "cash_net_movement": "-64576.00",
            },
            estimated_income_statement={
                "revenue": "251415.93",
                "cost": "226274.34",
                "expense": "10387.26",
                "operating_profit": "14754.33",
                "net_profit": "14754.33",
            },
        )
    )
    db_session.add(
        TaxFilingDraft(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            data={
                "output_amount": "251415.93",
                "output_tax": "32684.07",
                "input_amount": "282218.70",
                "input_tax": "36544.80",
                "vat_payable": "0.00",
                "unmatched_invoice_count": 12,
            },
            status="DRAFT",
        )
    )
    db_session.commit()

    class FakeHealthAiClient:
        def generate_report(self, payload):
            return {
                "sections": [
                    {"title": "一、报告摘要与核心结论", "content": ["企业资产负债率偏高，应优先复核应付账款与资金安排。"]},
                    {"title": "三、偿债能力分析", "content": ["短期偿债能力受现金余额和应付规模共同影响。"]},
                    {"title": "八、改进建议与应对措施", "content": ["建议三个月内完成发票、流水和往来款的专项清理。"]},
                ]
            }

    report = generate_health_report(
        db_session,
        monthly_work_package_id=package.id,
        output_dir=tmp_path,
        ai_client=FakeHealthAiClient(),
    )

    assert report.export_path is not None
    pdf_path = Path(report.export_path)
    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"
    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    compact_text = text.replace(" ", "")
    assert len(reader.pages) == 20
    assert "FINANCIALHEALTHDIAGNOSTIC" in compact_text
    assert "企业财务健康诊断报告" in text
    assert "总结展望" in text


def test_health_report_ai_payload_follows_sample_report_sections():
    payload = build_health_report_ai_payload(
        enterprise={"name": "苏州样例科技有限公司", "industry": "制造业", "unified_social_credit_code": "91320500REPORT000001"},
        period="2026-05",
        statement={
            "estimated_balance_sheet": {"total_assets": "48000000.00", "total_liabilities": "26000000.00"},
            "estimated_income_statement": {"revenue": "1200000.00", "operating_profit": "320000.00"},
        },
        tax_draft={"vat_payable": "7800.00"},
    )

    assert payload["report_structure"][0] == "执行摘要与关键结论"
    assert "风险等级总览矩阵" in payload["report_structure"]
    assert "税务风险与合规提示" in payload["report_structure"]
    assert "苏州样例科技有限公司" not in str(payload)
    assert "91320500REPORT000001" not in str(payload)


def test_moonshot_health_report_client_caps_completion_size():
    source = Path("app/services/report_service.py").read_text(encoding="utf-8")
    config_source = Path("app/core/config.py").read_text(encoding="utf-8")

    assert '"max_tokens": 3500' in source
    assert "每个章节输出1到2段" in source
    assert "不要自行换算金额单位" in source
    assert 'moonshot_report_model: str = "moonshot-v1-8k"' in config_source
    assert "model=settings.moonshot_report_model" in source


def test_report_html_endpoint_serves_online_health_report(db_session, tmp_path):
    enterprise, package = make_package(db_session)
    db_session.add(
        MonthlyStatement(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            estimated_balance_sheet={"total_assets": "48000000.00"},
            estimated_income_statement={"revenue": "1200000.00"},
        )
    )
    db_session.add(
        TaxFilingDraft(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            data={"vat_payable": "7800.00"},
            status="DRAFT",
        )
    )
    db_session.commit()
    report = generate_health_report(db_session, monthly_work_package_id=package.id, output_dir=tmp_path)
    app = create_app(init_db_on_startup=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(f"/api/reports/{report.id}/html")

    assert response.status_code == 200
    assert enterprise.name in response.text
    assert "执行摘要与关键结论" in response.text


def test_report_pdf_endpoint_serves_generated_health_report(db_session, tmp_path):
    enterprise, package = make_package(db_session)
    db_session.add(
        MonthlyStatement(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            estimated_balance_sheet={"total_assets": "48000000.00", "total_liabilities": "26000000.00"},
            estimated_income_statement={"revenue": "1200000.00", "operating_profit": "320000.00"},
        )
    )
    db_session.add(
        TaxFilingDraft(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            data={"vat_payable": "7800.00"},
            status="DRAFT",
        )
    )
    db_session.commit()
    report = generate_health_report(db_session, monthly_work_package_id=package.id, output_dir=tmp_path)
    app = create_app(init_db_on_startup=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(f"/api/reports/{report.id}/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert enterprise.name.encode("utf-8") not in response.content
