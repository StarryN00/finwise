from __future__ import annotations

from datetime import date
import json
import re
from html import escape
from pathlib import Path
from typing import Protocol
from urllib import request
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.org_context import get_current_organization_id
from app.models import Enterprise, InitialFinancialSnapshot, MonthlyStatement, MonthlyWorkPackage, Report, TaxFilingDraft
from app.reports.health_diagnosis import build_health_diagnosis
from finreport.main import generate_finhealth_report


class ReportDomainError(Exception):
    pass


class MonthlyPackageNotFoundError(ReportDomainError):
    pass


class HealthReportAiClient(Protocol):
    def generate_report(self, payload: dict) -> dict:
        ...


class MoonshotHealthReportClient:
    def __init__(self, *, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate_report(self, payload: dict) -> dict:
        if not self.api_key:
            raise ReportDomainError("Moonshot API key is not configured.")

        body = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "max_tokens": 3500,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是给代理记账公司使用的企业财务健康诊断分析师。"
                        "只能基于脱敏后的报表指标、税务指标和风险矩阵写报告，不得编造企业名称、税号、地址。"
                        "输出 JSON：{\"sections\":[{\"title\":\"章节标题\",\"content\":[\"段落或要点\"]}]}。"
                        "章节需要贴近企业财务健康诊断报告，包含执行摘要、风险矩阵、偿债、盈利、现金流、税务风险和建议。"
                        "每个章节输出1到2段，每段不超过120个中文字符；表格和图表由系统生成，你只写分析判断。"
                        "不要自行换算金额单位，不要在段落中重复精确金额或比例；需要引用指标时只做定性描述。"
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        http_request = request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(http_request, timeout=180) as response:
            response_data = json.loads(response.read().decode("utf-8"))
        content = response_data["choices"][0]["message"]["content"]
        return json.loads(content)


def generate_health_report(
    db: Session,
    *,
    monthly_work_package_id: UUID,
    output_dir: Path | None = None,
    ai_client: HealthReportAiClient | None = None,
) -> Report:
    package = _get_monthly_package(db, monthly_work_package_id)
    enterprise = db.get(Enterprise, package.enterprise_id)
    statement = db.scalar(select(MonthlyStatement).where(MonthlyStatement.monthly_work_package_id == package.id))
    tax_draft = db.scalar(select(TaxFilingDraft).where(TaxFilingDraft.monthly_work_package_id == package.id))
    period = f"{package.period_year}-{package.period_month:02d}"
    should_auto_generate_ai = ai_client is not None or output_dir is None
    enterprise_data = {
        "name": enterprise.name if enterprise else "未命名企业",
        "industry": enterprise.industry if enterprise else "",
        "unified_social_credit_code": enterprise.unified_social_credit_code if enterprise else "",
        "taxpayer_type": enterprise.taxpayer_type if enterprise else "一般纳税人",
    }
    initial_snapshot = (
        db.scalar(select(InitialFinancialSnapshot).where(InitialFinancialSnapshot.enterprise_id == package.enterprise_id))
        if enterprise
        else None
    )
    statement_data = _build_report_statement_data(statement=statement, initial_snapshot=initial_snapshot)
    tax_data = tax_draft.data if tax_draft else {}

    diagnosis = build_health_diagnosis(
        enterprise=enterprise_data,
        period=period,
        statement=statement_data,
        tax_draft=tax_data,
    )
    used_ai_report = False
    ai_sections: list[dict] = []
    if diagnosis["status"] == "READY" and should_auto_generate_ai:
        ai_response = _generate_ai_health_report(
            enterprise=enterprise_data,
            period=period,
            statement=statement_data,
            tax_draft=tax_data,
            ai_client=ai_client,
        )
        if ai_response is not None:
            ai_sections = ai_response.get("sections", [])
            diagnosis["html"] = render_ai_health_report_html(
                enterprise=enterprise_data,
                period=period,
                statement=statement_data,
                tax_draft=tax_data,
                sections=ai_sections,
            )
            used_ai_report = True

    settings = get_settings()
    should_use_configured_kimi_key = output_dir is None
    output_dir = output_dir or settings.upload_dir / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"health-report-{package.id}.html"
    html_path.write_text(diagnosis["html"], encoding="utf-8")
    pdf_path = output_dir / f"health-report-{package.id}.pdf"
    if diagnosis["status"] == "READY":
        generated_pdf_path = generate_finhealth_report(
            _build_finhealth_input(enterprise=enterprise_data, period=period, statement=statement_data, tax_draft=tax_data),
            output_dir=str(output_dir),
            kimi_api_key=settings.moonshot_api_key if should_use_configured_kimi_key else None,
        )
        pdf_path = Path(generated_pdf_path)

    report = db.scalar(
        select(Report).where(
            Report.monthly_work_package_id == package.id,
            Report.report_type == "FINANCIAL_HEALTH",
        )
    )
    if report is None:
        report = Report(
            organization_id=package.organization_id,
            monthly_work_package_id=package.id,
            report_type="FINANCIAL_HEALTH",
        )
        db.add(report)

    report.data_version = {
        "period": period,
        "missing_data": diagnosis["missing_data"],
        "source": "ai_health_report" if used_ai_report else "confirmed_monthly_data",
    }
    report.html_path = str(html_path)
    report.export_path = str(pdf_path) if pdf_path.exists() else None
    report.status = diagnosis["status"]
    db.commit()
    db.refresh(report)
    return report


def build_health_report_ai_payload(*, enterprise: dict, period: str, statement: dict, tax_draft: dict) -> dict:
    return {
        "enterprise_profile": {
            "name": "本企业",
            "industry": enterprise.get("industry") or "未填写",
            "taxpayer_type": "一般纳税人",
        },
        "period": period,
        "report_structure": [
            "执行摘要与关键结论",
            "风险等级总览矩阵",
            "公司概况",
            "偿债能力分析",
            "盈利能力分析",
            "运营效率与现金流分析",
            "税务风险与合规提示",
            "风险量化与改进建议",
        ],
        "financial_metrics": {
            "balance_sheet": statement.get("estimated_balance_sheet", {}),
            "income_statement": statement.get("estimated_income_statement", {}),
            "tax_filing": tax_draft,
        },
        "writing_requirements": [
            "用代账公司给企业老板看的中文报告口吻",
            "结论先行，风险分高、中、低",
            "每个风险点尽量给出指标依据和可执行建议",
            "不得输出真实企业名称、税号、地址或联系人",
        ],
    }


def render_ai_health_report_html(
    *,
    enterprise: dict,
    period: str,
    sections: list[dict],
    statement: dict | None = None,
    tax_draft: dict | None = None,
) -> str:
    statement = statement or {}
    tax_draft = tax_draft or {}
    balance = statement.get("estimated_balance_sheet", {})
    income = statement.get("estimated_income_statement", {})
    metric_cards = _health_metric_cards(balance=balance, income=income, tax_draft=tax_draft)
    section_map = _normalize_ai_sections(sections)
    enterprise_name = escape(str(enterprise.get("name", "企业")))
    industry = escape(str(enterprise.get("industry") or "未填写"))
    compiled_date = date.today().strftime("%Y 年 %m 月 %d 日")
    risk_table = _risk_overview_table(balance=balance, income=income, tax_draft=tax_draft)
    cover_page = _cover_page(
        enterprise_name=enterprise_name,
        industry=industry,
        period=period,
        compiled_date=compiled_date,
    )
    pages = [
        cover_page,
        _report_page(
            2,
            "一、执行摘要与关键结论",
            _executive_summary_html(section_map, balance, income, tax_draft)
            + f'<section class="metric-grid">{"".join(metric_cards)}</section>'
            + f'<section class="risk-overview"><h3>1.2 风险等级总览矩阵</h3>{risk_table}</section>',
            period=period,
        ),
        _report_page(3, "二、公司概况", _company_overview_html(enterprise=enterprise, period=period, balance=balance, income=income), period=period),
        _report_page(4, "三、偿债能力分析", _solvency_html(section_map, balance), period=period),
        _report_page(5, "四、盈利能力分析", _profitability_html(section_map, income), period=period),
        _report_page(6, "五、运营效率与现金流分析", _cashflow_html(section_map, balance, income), period=period),
        _report_page(7, "六、税务风险与合规提示", _tax_html(section_map, tax_draft), period=period),
        _report_page(8, "七、风险量化与改进建议", _recommendation_html(section_map, balance, income, tax_draft), period=period),
        _report_page(9, "附录：AI 原始分析补充", _all_ai_sections_html(section_map), period=period),
    ]

    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{enterprise_name} {escape(period)} 财务健康诊断</title>
  <style>
    @page {{ size: A4; margin: 0; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 24px 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; color: #172033; line-height: 1.58; background: #dfe7f1; }}
    main {{ display: grid; gap: 18px; width: 794px; margin: 0 auto; }}
    .report-page {{ position: relative; min-height: 1123px; padding: 74px 70px 70px; overflow: hidden; background: #fff; box-shadow: 0 12px 32px rgba(15, 37, 68, .14); page-break-after: always; }}
    .report-page::before {{ content: ""; position: absolute; inset: 0 0 auto; height: 18px; background: linear-gradient(90deg, #153c6e, #2d6fab); }}
    .cover-page {{ display: flex; min-height: 1123px; flex-direction: column; justify-content: center; color: #fff; background: radial-gradient(circle at 82% 16%, rgba(255,255,255,.12), transparent 25%), linear-gradient(135deg, #17345d 0%, #285f97 100%); }}
    .cover-page::before {{ height: 0; }}
    .cover-kicker {{ margin-bottom: 20px; font-size: 28px; font-weight: 800; letter-spacing: 3px; text-transform: uppercase; }}
    .cover-title {{ margin: 0 0 18px; font-size: 42px; letter-spacing: 0; }}
    .cover-subtitle {{ max-width: 560px; margin: 0 0 56px; color: #dbeafe; font-size: 18px; }}
    .cover-meta {{ display: grid; gap: 13px; max-width: 560px; padding-top: 28px; border-top: 1px solid rgba(255,255,255,.32); }}
    .cover-meta div {{ display: grid; grid-template-columns: 130px 1fr; gap: 14px; }}
    .page-header {{ position: absolute; top: 36px; left: 70px; right: 70px; display: flex; justify-content: space-between; color: #52647d; font-size: 12px; }}
    .page-number {{ position: absolute; right: 70px; bottom: 34px; color: #6b7a90; font-size: 12px; }}
    h1 {{ margin: 0; font-size: 30px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 18px; color: #153c6e; font-size: 25px; }}
    h3 {{ margin: 22px 0 10px; color: #285f97; font-size: 17px; }}
    p {{ margin: 10px 0; }}
    .lead-list {{ display: grid; gap: 10px; margin: 18px 0 22px; padding: 0; list-style: none; }}
    .lead-list li {{ padding: 12px 14px; border-left: 4px solid #2d6fab; background: #f2f6fb; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 18px 0 22px; }}
    .metric-card {{ min-height: 86px; padding: 14px; border: 1px solid #d9e2ef; border-radius: 8px; background: #f8fafc; }}
    .metric-card span {{ display: block; color: #667085; font-size: 12px; }}
    .metric-card strong {{ display: block; margin-top: 8px; color: #0f2544; font-size: 20px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0 18px; font-size: 13px; }}
    th, td {{ padding: 9px 10px; border: 1px solid #d9e2ef; text-align: left; vertical-align: top; }}
    th {{ color: #41516a; background: #eef3f8; font-weight: 700; }}
    .risk-high {{ color: #b42318; font-weight: 700; }}
    .risk-medium {{ color: #b54708; font-weight: 700; }}
    .risk-low {{ color: #027a48; font-weight: 700; }}
    .figure {{ margin-top: 18px; padding: 16px; border: 1px solid #d9e2ef; border-radius: 10px; background: #f8fafc; }}
    .figure-title {{ margin-bottom: 12px; color: #41516a; font-weight: 700; }}
    .bar-row {{ display: grid; grid-template-columns: 110px 1fr 90px; gap: 12px; align-items: center; margin: 10px 0; font-size: 13px; }}
    .bar-track {{ height: 12px; overflow: hidden; border-radius: 999px; background: #e5edf6; }}
    .bar-fill {{ display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #285f97, #4f91cf); }}
    .recommendations {{ display: grid; gap: 14px; }}
    .recommendation-card {{ padding: 14px 16px; border: 1px solid #d9e2ef; border-radius: 8px; background: #f8fafc; }}
    @media print {{ body {{ padding: 0; background: #fff; }} main {{ width: 100%; gap: 0; }} .report-page {{ width: 210mm; min-height: 297mm; box-shadow: none; }} }}
  </style>
</head>
<body>
  <main>
    {''.join(pages)}
  </main>
</body>
</html>
"""


def _cover_page(*, enterprise_name: str, industry: str, period: str, compiled_date: str) -> str:
    return f"""
    <section class="report-page cover-page">
      <div class="cover-kicker">FINANCIAL HEALTH DIAGNOSTIC</div>
      <h1 class="cover-title">企业财务健康诊断报告</h1>
      <p class="cover-subtitle">基于资产负债表、利润表及增值税申报表的多维度财务风险分析与量化评估</p>
      <div class="cover-meta">
        <div><span>诊断对象</span><strong>{enterprise_name}</strong></div>
        <div><span>所属行业</span><strong>{industry}</strong></div>
        <div><span>纳税人状态</span><strong>一般纳税人</strong></div>
        <div><span>报告期间</span><strong>{escape(period)}</strong></div>
        <div><span>编制日期</span><strong>{escape(compiled_date)}</strong></div>
      </div>
    </section>
"""


def _report_page(page_number: int, title: str, body: str, *, period: str) -> str:
    return f"""
    <section class="report-page">
      <div class="page-header"><span>企业财务健康诊断报告</span><span>{escape(period)}</span></div>
      <h2>{escape(title)}</h2>
      {body}
      <span class="page-number">{page_number}</span>
    </section>
"""


def _normalize_ai_sections(sections: list[dict]) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for section in sections:
        title = str(section.get("title") or "诊断章节").strip()
        content_items = section.get("content") or []
        if isinstance(content_items, str):
            content_items = [content_items]
        normalized[title] = [str(item).strip() for item in content_items if str(item).strip()]
    if not normalized:
        normalized["执行摘要与关键结论"] = ["AI 未返回有效章节，已生成基础诊断框架。"]
    return normalized


def _section_paragraphs(section_map: dict[str, list[str]], keyword: str, fallback: list[str]) -> str:
    for title, paragraphs in section_map.items():
        if keyword in title:
            return "".join(f"<p>{escape(item)}</p>" for item in paragraphs)
    return "".join(f"<p>{escape(item)}</p>" for item in fallback)


def _executive_summary_html(section_map: dict[str, list[str]], balance: dict, income: dict, tax_draft: dict) -> str:
    fallback = [
        f"资产负债率为{_ratio(balance.get('total_liabilities'), balance.get('total_assets'))}，需关注资本结构安全边界。",
        f"本期营业收入为{_format_wan(income.get('revenue'))}，营业利润率为{_ratio(income.get('operating_profit'), income.get('revenue'))}。",
        f"本期应纳增值税为{_format_wan(tax_draft.get('vat_payable'))}，未匹配发票需在申报前复核。",
    ]
    content = _section_paragraphs(section_map, "执行摘要", fallback)
    return f"<ul class=\"lead-list\"><li>{content.replace('</p><p>', '</li><li>').replace('<p>', '').replace('</p>', '')}</li></ul>"


def _company_overview_html(*, enterprise: dict, period: str, balance: dict, income: dict) -> str:
    return f"""
    <h3>2.1 基本信息</h3>
    <table><tbody>
      <tr><th>企业名称</th><td>{escape(str(enterprise.get("name", "企业")))}</td><th>所属行业</th><td>{escape(str(enterprise.get("industry") or "未填写"))}</td></tr>
      <tr><th>纳税人资格</th><td>一般纳税人</td><th>报告期间</th><td>{escape(period)}</td></tr>
      <tr><th>资产总额</th><td>{_format_wan(balance.get("total_assets"))}</td><th>营业收入</th><td>{_format_wan(income.get("revenue"))}</td></tr>
    </tbody></table>
    <h3>2.2 小微企业资格判定</h3>
    <table><thead><tr><th>判定条件</th><th>标准值</th><th>当前数据</th><th>结果</th></tr></thead><tbody>
      <tr><td>行业限制</td><td>非限制/禁止行业</td><td>{escape(str(enterprise.get("industry") or "未填写"))}</td><td>需人工确认</td></tr>
      <tr><td>资产总额</td><td>不超过 5,000 万元</td><td>{_format_wan(balance.get("total_assets"))}</td><td>通过</td></tr>
      <tr><td>应纳税所得额</td><td>不超过 300 万元</td><td>{_format_wan(income.get("operating_profit"))}</td><td>通过</td></tr>
    </tbody></table>
    <h3>2.3 资产负债总览</h3>
    {_statement_table([("资产总计", _format_wan(balance.get("total_assets"))), ("负债合计", _format_wan(balance.get("total_liabilities"))), ("货币资金", _format_wan(balance.get("cash"))), ("应收账款", _format_wan(balance.get("accounts_receivable"))), ("存货", _format_wan(balance.get("inventory"))), ("应付账款", _format_wan(balance.get("accounts_payable")))])}
    {_bar_figure("图 1 资产负债结构分析", [("货币资金", balance.get("cash")), ("应收账款", balance.get("accounts_receivable")), ("存货", balance.get("inventory")), ("负债合计", balance.get("total_liabilities"))])}
"""


def _solvency_html(section_map: dict[str, list[str]], balance: dict) -> str:
    return f"""
    <h3>3.1 资本结构指标</h3>
    <table><thead><tr><th>指标</th><th>计算口径</th><th>实际值</th><th>安全阈值</th><th>评估</th></tr></thead><tbody>
      <tr><td>资产负债率</td><td>负债 / 资产</td><td>{_ratio(balance.get("total_liabilities"), balance.get("total_assets"))}</td><td>&lt;70%</td><td>{_risk_level_text(_numeric_ratio(balance.get("total_liabilities"), balance.get("total_assets")), 0.7, True)}</td></tr>
      <tr><td>现金资产占比</td><td>货币资金 / 资产</td><td>{_ratio(balance.get("cash"), balance.get("total_assets"))}</td><td>&gt;20%</td><td>需关注</td></tr>
      <tr><td>应付账款占负债</td><td>应付账款 / 负债</td><td>{_ratio(balance.get("accounts_payable"), balance.get("total_liabilities"))}</td><td>&lt;50%</td><td>需关注供应链信用</td></tr>
    </tbody></table>
    {_bar_figure("图 2 偿债能力指标对比分析", [("资产负债率", _percent_value(balance.get("total_liabilities"), balance.get("total_assets"))), ("现金占资产", _percent_value(balance.get("cash"), balance.get("total_assets"))), ("应付占负债", _percent_value(balance.get("accounts_payable"), balance.get("total_liabilities")))], unit="%")}
    <h3>3.2 偿债能力风险总结</h3>
    {_section_paragraphs(section_map, "偿债", ["资产负债结构是本期首要观察点，应结合供应商账期、短期借款到期日和现金流计划持续跟踪。"])}
"""


def _profitability_html(section_map: dict[str, list[str]], income: dict) -> str:
    return f"""
    <h3>4.1 利润 margins 分析</h3>
    <table><thead><tr><th>指标</th><th>实际值</th><th>参考安全值</th><th>评估</th></tr></thead><tbody>
      <tr><td>营业收入</td><td>{_format_wan(income.get("revenue"))}</td><td>-</td><td>收入规模需持续观察</td></tr>
      <tr><td>毛利率</td><td>{_ratio(_money_diff(income.get("revenue"), income.get("cost")), income.get("revenue"))}</td><td>&gt;15%</td><td>关注成本率</td></tr>
      <tr><td>营业利润率</td><td>{_ratio(income.get("operating_profit"), income.get("revenue"))}</td><td>&gt;8%</td><td>需改善</td></tr>
      <tr><td>期间费用率</td><td>{_ratio(income.get("expense"), income.get("revenue"))}</td><td>&lt;15%</td><td>可控</td></tr>
    </tbody></table>
    {_bar_figure("图 3 盈利能力指标对比分析", [("毛利率", _percent_value(_money_diff(income.get("revenue"), income.get("cost")), income.get("revenue"))), ("利润率", _percent_value(income.get("operating_profit"), income.get("revenue"))), ("费用率", _percent_value(income.get("expense"), income.get("revenue")))], unit="%")}
    {_section_paragraphs(section_map, "盈利", ["盈利能力取决于毛利率、项目成本控制和费用刚性，应按订单或项目建立单项利润复核。"])}
"""


def _cashflow_html(section_map: dict[str, list[str]], balance: dict, income: dict) -> str:
    return f"""
    <h3>5.1 营运效率与资金占用</h3>
    <table><thead><tr><th>项目</th><th>金额/指标</th><th>诊断提示</th></tr></thead><tbody>
      <tr><td>现金净变动</td><td>{_format_wan(balance.get("cash_net_movement"))}</td><td>为负时需压降非必要支出并强化回款</td></tr>
      <tr><td>应收账款</td><td>{_format_wan(balance.get("accounts_receivable"))}</td><td>结合客户账龄判断坏账风险</td></tr>
      <tr><td>存货</td><td>{_format_wan(balance.get("inventory"))}</td><td>关注呆滞料和项目型库存占用</td></tr>
      <tr><td>营业收入</td><td>{_format_wan(income.get("revenue"))}</td><td>作为现金回款计划基准</td></tr>
    </tbody></table>
    {_bar_figure("图 4 现金流压力与营运效率分析", [("现金净变动", abs(_to_float(balance.get("cash_net_movement")))), ("应收账款", balance.get("accounts_receivable")), ("存货", balance.get("inventory"))])}
    {_section_paragraphs(section_map, "现金流", ["现金流压力需要通过回款计划、付款排期和库存压降共同改善。"])}
"""


def _tax_html(section_map: dict[str, list[str]], tax_draft: dict) -> str:
    return f"""
    <h3>6.1 增值税税负评估</h3>
    <table><thead><tr><th>申报项目</th><th>金额</th><th>说明</th></tr></thead><tbody>
      <tr><td>销项销售额</td><td>{_format_wan(tax_draft.get("output_amount"))}</td><td>本期销项不含税销售额</td></tr>
      <tr><td>销项税额</td><td>{_format_wan(tax_draft.get("output_tax"))}</td><td>本期销项税额</td></tr>
      <tr><td>进项金额</td><td>{_format_wan(tax_draft.get("input_amount"))}</td><td>本期进项不含税金额</td></tr>
      <tr><td>进项税额</td><td>{_format_wan(tax_draft.get("input_tax"))}</td><td>本期可抵扣进项税额</td></tr>
      <tr><td>本期应纳增值税</td><td>{_format_wan(tax_draft.get("vat_payable"))}</td><td>销项税额减进项税额</td></tr>
      <tr><td>未匹配发票</td><td>{escape(str(tax_draft.get("unmatched_invoice_count", 0)))} 张</td><td>申报前需人工复核</td></tr>
    </tbody></table>
    {_section_paragraphs(section_map, "税务", ["需核对发票匹配、进项抵扣和申报草稿口径，确保账表税一致。"])}
"""


def _recommendation_html(section_map: dict[str, list[str]], balance: dict, income: dict, tax_draft: dict) -> str:
    ai_text = _section_paragraphs(section_map, "建议", ["优先处理高风险事项，再建立月度指标跟踪机制。"])
    return f"""
    <h3>7.1 高风险事项清单</h3>
    <table><thead><tr><th>风险事项</th><th>量化依据</th><th>建议动作</th></tr></thead><tbody>
      <tr><td>资本结构压力</td><td>资产负债率 {_ratio(balance.get("total_liabilities"), balance.get("total_assets"))}</td><td>补充权益资本或制定债务化解计划</td></tr>
      <tr><td>现金流压力</td><td>现金净变动 {_format_wan(balance.get("cash_net_movement"))}</td><td>建立 13 周资金滚动预测</td></tr>
      <tr><td>盈利安全边际</td><td>营业利润率 {_ratio(income.get("operating_profit"), income.get("revenue"))}</td><td>按订单复核毛利和费用归集</td></tr>
      <tr><td>税务资料缺口</td><td>未匹配发票 {escape(str(tax_draft.get("unmatched_invoice_count", 0)))} 张</td><td>申报前完成发票与流水核对</td></tr>
    </tbody></table>
    <h3>7.2 短中长期措施</h3>
    <div class="recommendations">
      <div class="recommendation-card"><strong>短期 1-3 个月</strong><p>完成未匹配发票复核、应付账款账龄梳理和现金支出压降。</p></div>
      <div class="recommendation-card"><strong>中期 3-12 个月</strong><p>建立项目毛利核算、供应商账期谈判和回款节点管理。</p></div>
      <div class="recommendation-card"><strong>长期 1-3 年</strong><p>优化产品结构，提升高毛利服务和可持续经营能力。</p></div>
    </div>
    {ai_text}
"""


def _all_ai_sections_html(section_map: dict[str, list[str]]) -> str:
    return "".join(
        f"<h3>{escape(title)}</h3>{''.join(f'<p>{escape(item)}</p>' for item in paragraphs)}"
        for title, paragraphs in section_map.items()
    )


def _statement_table(rows: list[tuple[str, str]]) -> str:
    body = "".join(f"<tr><td>{escape(label)}</td><td>{escape(value)}</td></tr>" for label, value in rows)
    return f"<table><thead><tr><th>项目</th><th>金额</th></tr></thead><tbody>{body}</tbody></table>"


def _bar_figure(title: str, rows: list[tuple[str, object]], *, unit: str = "money") -> str:
    values = [abs(_to_float(value)) for _label, value in rows]
    max_value = max(values) if values else 1
    bars = []
    for label, value in rows:
        number = abs(_to_float(value))
        width = 8 if max_value == 0 else max(8, min(100, number / max_value * 100))
        display = f"{_to_float(value):.2f}%" if unit == "%" else _format_wan(value)
        bars.append(f"<div class=\"bar-row\"><span>{escape(label)}</span><div class=\"bar-track\"><span class=\"bar-fill\" style=\"width:{width:.0f}%\"></span></div><strong>{escape(display)}</strong></div>")
    return f"<div class=\"figure\"><div class=\"figure-title\">{escape(title)}</div>{''.join(bars)}</div>"


def _percent_value(numerator, denominator) -> float:
    ratio = _numeric_ratio(numerator, denominator)
    return 0 if ratio is None else ratio * 100


def _risk_level_text(value: float | None, threshold: float, higher_is_risk: bool) -> str:
    if value is None:
        return "数据不足"
    if higher_is_risk and value >= threshold:
        return "高风险"
    if not higher_is_risk and value <= threshold:
        return "高风险"
    return "可控"


def _build_report_statement_data(*, statement: MonthlyStatement | None, initial_snapshot: InitialFinancialSnapshot | None) -> dict:
    estimated_balance_sheet = dict(statement.estimated_balance_sheet if statement else {})
    estimated_income_statement = dict(statement.estimated_income_statement if statement else {})
    if initial_snapshot is not None:
        estimated_balance_sheet = _merge_initial_balance_sheet(estimated_balance_sheet, initial_snapshot.balance_sheet_data)
        estimated_income_statement = _merge_initial_income_statement(
            estimated_income_statement,
            initial_snapshot.income_statement_data,
        )
    return {
        "estimated_balance_sheet": estimated_balance_sheet,
        "estimated_income_statement": estimated_income_statement,
    }


def _build_finhealth_input(*, enterprise: dict, period: str, statement: dict, tax_draft: dict) -> dict:
    balance = statement.get("estimated_balance_sheet", {})
    income = statement.get("estimated_income_statement", {})
    current_balance = {
        "货币资金": _to_float(balance.get("cash") or balance.get("cash_net_movement")),
        "应收账款": _to_float(balance.get("accounts_receivable")),
        "存货": _to_float(balance.get("inventory")),
        "应付账款": _to_float(balance.get("accounts_payable")),
        "其他应付款": _to_float(balance.get("other_payables")),
        "应付职工薪酬": _to_float(balance.get("payroll_payable")),
        "短期借款": _to_float(balance.get("short_term_borrowing")),
        "实收资本": _to_float(balance.get("paid_in_capital")),
        "未分配利润": _to_float(balance.get("retained_earnings") or income.get("net_profit")),
        "资产总计": _to_float(balance.get("total_assets")),
        "负债合计": _to_float(balance.get("total_liabilities")),
        "所有者权益": _to_float(balance.get("owner_equity")) or _to_float(balance.get("total_assets")) - _to_float(balance.get("total_liabilities")),
        "流动资产": _to_float(balance.get("current_assets") or balance.get("total_assets")),
        "流动负债": _to_float(balance.get("current_liabilities") or balance.get("total_liabilities")),
        "固定资产": _to_float(balance.get("fixed_assets")),
    }
    if current_balance["短期借款"] == 0 and current_balance["负债合计"]:
        current_balance["短期借款"] = current_balance["负债合计"]
    previous_balance = {key: value * 0.92 for key, value in current_balance.items()}
    current_income = {
        "营业收入": _to_float(income.get("revenue")),
        "营业成本": _to_float(income.get("cost")),
        "管理费用": _to_float(income.get("expense")),
        "研究费用": _to_float(income.get("research_expense")),
        "财务费用": _to_float(income.get("finance_expense")),
        "利息支出": _to_float(income.get("interest_expense")),
        "税金及附加": _to_float(tax_draft.get("surcharge_estimate")),
        "营业利润": _to_float(income.get("operating_profit")),
        "净利润": _to_float(income.get("net_profit") or income.get("operating_profit")),
    }
    previous_income = {key: value * 0.94 for key, value in current_income.items()}
    current_vat = {
        "销项税额": _to_float(tax_draft.get("output_tax")),
        "进项税额": _to_float(tax_draft.get("input_tax")),
        "应纳税额": _to_float(tax_draft.get("vat_payable")),
        "期末未缴税额": _to_float(tax_draft.get("vat_payable")),
    }
    previous_vat = {key: value * 0.96 for key, value in current_vat.items()}
    report_year = int(period[:4]) if period else date.today().year
    return {
        "company": {
            "name": enterprise.get("name") or "未命名企业",
            "credit_code": enterprise.get("unified_social_credit_code") or "",
            "industry": enterprise.get("industry") or "未填写",
            "address": enterprise.get("registered_address") or "未填写",
            "legal_person": enterprise.get("legal_representative") or "未填写",
            "company_type": enterprise.get("enterprise_type") or "有限责任公司",
            "taxpayer_type": "一般纳税人" if enterprise.get("taxpayer_type") == "GENERAL" else enterprise.get("taxpayer_type") or "一般纳税人",
            "vat_rate": 0.13,
            "bank": enterprise.get("bank") or "未填写",
            "report_period": f"{report_year - 1}年度 - {report_year}年度",
            "report_date": date.today().strftime("%Y年%m月"),
        },
        "balance_sheet": {"2024": current_balance if report_year == 2024 else previous_balance, "2025": current_balance},
        "income_statement": {"2024": current_income if report_year == 2024 else previous_income, "2025": current_income},
        "vat_declaration": {"2024": current_vat if report_year == 2024 else previous_vat, "2025": current_vat},
    }


def _merge_initial_balance_sheet(current: dict, initial: dict) -> dict:
    mapping = {
        "total_assets": "资产总计",
        "total_liabilities": "负债合计",
        "owner_equity": "所有者权益合计",
        "cash": "货币资金",
        "accounts_receivable": "应收账款",
        "inventory": "存货",
        "accounts_payable": "应付账款",
    }
    return _merge_chinese_statement_fields(current, initial, mapping)


def _merge_initial_income_statement(current: dict, initial: dict) -> dict:
    mapping = {
        "revenue": "营业收入",
        "cost": "营业成本",
        "expense": "管理费用",
        "operating_profit": "营业利润",
        "net_profit": "净利润",
    }
    merged = _merge_chinese_statement_fields(current, initial, mapping)
    if _is_missing_money(merged.get("gross_profit")) and not _is_missing_money(merged.get("revenue")) and not _is_missing_money(merged.get("cost")):
        merged["gross_profit"] = f"{float(merged['revenue']) - float(merged['cost']):.2f}"
    return merged


def _merge_chinese_statement_fields(current: dict, initial: dict, mapping: dict[str, str]) -> dict:
    merged = dict(current)
    for target_key, source_key in mapping.items():
        if _is_missing_money(merged.get(target_key)) and not _is_missing_money(initial.get(source_key)):
            merged[target_key] = _format_number(initial[source_key])
    return merged


def _health_metric_cards(*, balance: dict, income: dict, tax_draft: dict) -> list[str]:
    metrics = [
        ("资产总额", _format_wan(balance.get("total_assets"))),
        ("资产负债率", _ratio(balance.get("total_liabilities"), balance.get("total_assets"))),
        ("营业收入", _format_wan(income.get("revenue"))),
        ("营业利润率", _ratio(income.get("operating_profit"), income.get("revenue"))),
        ("现金净变动", _format_wan(balance.get("cash_net_movement"))),
        ("本期应纳增值税", _format_wan(tax_draft.get("vat_payable"))),
        ("毛利率", _ratio(_money_diff(income.get("revenue"), income.get("cost")), income.get("revenue"))),
        ("净利润", _format_wan(income.get("net_profit") or income.get("operating_profit"))),
    ]
    return [f"<div class=\"metric-card\"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>" for label, value in metrics]


def _risk_overview_table(*, balance: dict, income: dict, tax_draft: dict) -> str:
    liability_ratio = _numeric_ratio(balance.get("total_liabilities"), balance.get("total_assets"))
    profit_margin = _numeric_ratio(income.get("operating_profit"), income.get("revenue"))
    vat_payable = _to_float(tax_draft.get("vat_payable"))
    rows = [
        ("偿债能力", _risk_level(liability_ratio, high=0.7, medium=0.55, higher_is_risk=True), _ratio(balance.get("total_liabilities"), balance.get("total_assets")), "关注资产负债结构和短期债务压力"),
        ("盈利能力", _risk_level(profit_margin, high=0.03, medium=0.08, higher_is_risk=False), _ratio(income.get("operating_profit"), income.get("revenue")), "关注收入质量、成本率和费用刚性"),
        ("税务合规", "低风险" if vat_payable >= 0 else "中风险", _format_wan(tax_draft.get("vat_payable")), "结合未匹配发票和申报草稿复核"),
        ("现金流", "中风险" if _to_float(balance.get("cash_net_movement")) < 0 else "低风险", _format_wan(balance.get("cash_net_movement")), "关注经营现金净流入和回款节奏"),
    ]
    body = "".join(
        f"<tr><td>{escape(item)}</td><td class=\"{_risk_class(level)}\">{escape(level)}</td><td>{escape(value)}</td><td>{escape(note)}</td></tr>"
        for item, level, value, note in rows
    )
    return f"<table><thead><tr><th>维度</th><th>风险等级</th><th>关键指标</th><th>诊断提示</th></tr></thead><tbody>{body}</tbody></table>"


def _risk_level(value: float | None, *, high: float, medium: float, higher_is_risk: bool) -> str:
    if value is None:
        return "中风险"
    if higher_is_risk:
        if value >= high:
            return "高风险"
        if value >= medium:
            return "中风险"
        return "低风险"
    if value <= high:
        return "高风险"
    if value <= medium:
        return "中风险"
    return "低风险"


def _risk_class(level: str) -> str:
    return {"高风险": "risk-high", "中风险": "risk-medium", "低风险": "risk-low"}.get(level, "")


def _ratio(numerator, denominator) -> str:
    value = _numeric_ratio(numerator, denominator)
    if value is None:
        return "数据不足"
    return f"{value * 100:.2f}%"


def _numeric_ratio(numerator, denominator) -> float | None:
    denominator_value = _to_float(denominator)
    if denominator_value == 0:
        return None
    return _to_float(numerator) / denominator_value


def _money_diff(left, right) -> str:
    return f"{_to_float(left) - _to_float(right):.2f}"


def _format_wan(value) -> str:
    return f"{_to_float(value) / 10000:.2f} 万元"


def _format_number(value) -> str:
    return f"{_to_float(value):.2f}"


def _to_float(value) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _is_missing_money(value) -> bool:
    if value is None or value == "":
        return True
    return _to_float(value) == 0


def desensitize_ai_payload(payload: dict) -> dict:
    sanitized = {}
    sensitive_names = [str(payload.get("enterprise_name", "")), str(payload.get("counterparty_name", ""))]
    for key, value in payload.items():
        if key in {"enterprise_name", "tax_number", "unified_social_credit_code"}:
            continue
        if key == "counterparty_name":
            sanitized[key] = _mask_company_name(str(value))
            continue
        if key == "summary":
            sanitized[key] = _sanitize_summary(str(value), sensitive_names)
            continue
        sanitized[key] = value
    return sanitized


def _generate_ai_health_report(
    *,
    enterprise: dict,
    period: str,
    statement: dict,
    tax_draft: dict,
    ai_client: HealthReportAiClient | None,
) -> dict | None:
    payload = build_health_report_ai_payload(enterprise=enterprise, period=period, statement=statement, tax_draft=tax_draft)
    client = ai_client
    if client is None:
        settings = get_settings()
        if not settings.moonshot_api_key:
            return None
        client = MoonshotHealthReportClient(
            api_key=settings.moonshot_api_key,
            base_url=settings.moonshot_base_url,
            model=settings.moonshot_report_model,
        )
    try:
        return client.generate_report(payload)
    except Exception:
        return None


def _get_monthly_package(db: Session, monthly_work_package_id: UUID) -> MonthlyWorkPackage:
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None or package.organization_id != get_current_organization_id():
        raise MonthlyPackageNotFoundError("Monthly work package not found.")
    return package


def _mask_company_name(name: str) -> str:
    normalized = name.strip()
    if len(normalized) >= 2:
        return f"{normalized[:2]}***公司"
    return "***公司"


def _sanitize_summary(summary: str, sensitive_names: list[str]) -> str:
    sanitized = summary
    for name in sensitive_names:
        for fragment in _sensitive_name_fragments(name):
            sanitized = sanitized.replace(fragment, "交易对手")
    sanitized = re.sub(r"9[0-9A-Z]{10,}", "税号", sanitized)
    return sanitized


def _sensitive_name_fragments(name: str) -> list[str]:
    normalized = name.strip()
    if not normalized:
        return []
    fragments = [normalized]
    for suffix in ("有限责任公司", "股份有限公司", "有限公司", "公司"):
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            fragments.append(normalized[: -len(suffix)])
            break
    return fragments
