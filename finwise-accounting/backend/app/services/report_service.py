from __future__ import annotations

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
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是给代理记账公司使用的企业财务健康诊断分析师。"
                        "只能基于脱敏后的报表指标、税务指标和风险矩阵写报告，不得编造企业名称、税号、地址。"
                        "输出 JSON：{\"sections\":[{\"title\":\"章节标题\",\"content\":[\"段落或要点\"]}]}。"
                        "章节需要贴近企业财务健康诊断报告，包含执行摘要、风险矩阵、偿债、盈利、现金流、税务风险和建议。"
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
    if diagnosis["status"] == "READY" and should_auto_generate_ai:
        ai_response = _generate_ai_health_report(
            enterprise=enterprise_data,
            period=period,
            statement=statement_data,
            tax_draft=tax_data,
            ai_client=ai_client,
        )
        if ai_response is not None:
            diagnosis["html"] = render_ai_health_report_html(
                enterprise=enterprise_data,
                period=period,
                statement=statement_data,
                tax_draft=tax_data,
                sections=ai_response.get("sections", []),
            )
            used_ai_report = True

    output_dir = output_dir or get_settings().upload_dir / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"health-report-{package.id}.html"
    html_path.write_text(diagnosis["html"], encoding="utf-8")

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
    section_html = []
    for section in sections:
        title = escape(str(section.get("title") or "诊断章节"))
        content_items = section.get("content") or []
        if isinstance(content_items, str):
            content_items = [content_items]
        paragraphs = "".join(f"<p>{escape(str(item))}</p>" for item in content_items if str(item).strip())
        section_html.append(f"<section><h2>{title}</h2>{paragraphs}</section>")
    if not section_html:
        section_html.append("<section><h2>执行摘要与关键结论</h2><p>AI 未返回有效章节，已生成基础诊断框架。</p></section>")

    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{escape(str(enterprise.get("name", "企业")))} {escape(period)} 财务健康诊断</title>
  <style>
    body {{ margin: 0; padding: 40px 28px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; color: #172033; line-height: 1.72; background: #eef3f8; }}
    main {{ max-width: 1080px; margin: 0 auto; }}
    header {{ padding: 34px 38px; border-radius: 16px; color: #fff; background: linear-gradient(135deg, #123c7c, #1769e0); }}
    h1 {{ margin: 0 0 8px; font-size: 30px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 14px; color: #123c7c; font-size: 20px; }}
    section {{ margin-top: 18px; padding: 26px 30px; border: 1px solid #d9e2ef; border-radius: 14px; background: #fff; }}
    p {{ margin: 10px 0; }}
    .subtitle {{ margin: 0; color: #dbeafe; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }}
    .metric-card {{ padding: 16px; border: 1px solid #d9e2ef; border-radius: 12px; background: #f8fafc; }}
    .metric-card span {{ display: block; color: #667085; font-size: 12px; }}
    .metric-card strong {{ display: block; margin-top: 8px; color: #0f2544; font-size: 22px; }}
    .risk-overview table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    .risk-overview th, .risk-overview td {{ padding: 11px 12px; border-bottom: 1px solid #e5edf6; text-align: left; }}
    .risk-overview th {{ color: #667085; background: #f8fafc; }}
    .risk-high {{ color: #b42318; font-weight: 700; }}
    .risk-medium {{ color: #b54708; font-weight: 700; }}
    .risk-low {{ color: #027a48; font-weight: 700; }}
    @media (max-width: 860px) {{ .metric-grid {{ grid-template-columns: 1fr 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{escape(str(enterprise.get("name", "企业")))} {escape(period)} 财务健康诊断报告</h1>
      <p class="subtitle">基于资产负债表、利润表、申报草稿及已确认账目，由 AI 生成多维度风险分析与建议。</p>
    </header>
    <section class="metric-grid">{''.join(metric_cards)}</section>
    <section class="risk-overview">
      <h2>风险等级总览矩阵</h2>
      {_risk_overview_table(balance=balance, income=income, tax_draft=tax_draft)}
    </section>
    {''.join(section_html)}
  </main>
</body>
</html>
"""


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
            model=settings.moonshot_model,
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
