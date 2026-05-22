from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html import escape


HEALTH_SECTIONS = [
    "执行摘要与关键结论",
    "企业概况",
    "偿债能力",
    "盈利能力",
    "运营效率与现金流",
    "税务风险",
    "风险量化",
    "建议",
]


def build_health_diagnosis(*, enterprise: dict, period: str, statement: dict, tax_draft: dict) -> dict:
    missing_data = _missing_data(statement=statement, tax_draft=tax_draft)
    status = "DATA_INSUFFICIENT" if missing_data else "READY"
    html = render_health_diagnosis_html(
        enterprise=enterprise,
        period=period,
        statement=statement,
        tax_draft=tax_draft,
        missing_data=missing_data,
    )
    return {"status": status, "missing_data": missing_data, "html": html}


def render_health_diagnosis_html(
    *,
    enterprise: dict,
    period: str,
    statement: dict,
    tax_draft: dict,
    missing_data: list[str] | None = None,
) -> str:
    missing_data = missing_data or []
    balance = statement.get("estimated_balance_sheet", {})
    income = statement.get("estimated_income_statement", {})
    tax = tax_draft or {}
    assets = _decimal(balance.get("total_assets"))
    liabilities = _decimal(balance.get("total_liabilities"))
    revenue = _decimal(income.get("revenue"))
    cost = _decimal(income.get("cost"))
    expense = _decimal(income.get("expense"))
    profit = _decimal(income.get("operating_profit"))
    vat_payable = _decimal(tax.get("vat_payable"))

    asset_liability_ratio = _percent(liabilities / assets) if assets else "数据不足"
    gross_margin = _percent((revenue - cost) / revenue) if revenue else "数据不足"
    operating_margin = _percent(profit / revenue) if revenue else "数据不足"
    missing_html = ""
    if missing_data:
        items = "".join(f"<li>{escape(item)}</li>" for item in missing_data)
        missing_html = f"<div class=\"alert\"><strong>数据不足</strong><ul>{items}</ul></div>"

    section_html = f"""
  <section><h2>执行摘要与关键结论</h2>{missing_html}<p>本报告基于已确认账目、申报草稿和月度估算表生成。</p></section>
  <section><h2>企业概况</h2><p>{escape(str(enterprise.get("name", "未命名企业")))}，所属行业：{escape(str(enterprise.get("industry", "未填写")))}。</p></section>
  <section><h2>偿债能力</h2><table><tr><th>指标</th><th>结果</th><th>安全值</th></tr><tr><td>资产负债率</td><td>{asset_liability_ratio}</td><td>&lt;70%</td></tr></table></section>
  <section><h2>盈利能力</h2><table><tr><th>指标</th><th>结果</th></tr><tr><td>毛利率</td><td>{gross_margin}</td></tr><tr><td>营业利润率</td><td>{operating_margin}</td></tr></table></section>
  <section><h2>运营效率与现金流</h2><p>现金净变动：{_wan(balance.get("cash_net_movement"))}万元；期间费用：{_wan(expense)}万元。</p></section>
  <section><h2>税务风险</h2><p>预计应纳增值税：{_wan(vat_payable)}万元；需在导出前核对未匹配发票和异常流水。</p></section>
  <section><h2>风险量化</h2><table><tr><th>风险项</th><th>潜在影响</th><th>依据</th></tr><tr><td>税务数据偏差</td><td>{_wan(vat_payable)}万元</td><td>本期应纳增值税</td></tr></table></section>
  <section><h2>建议</h2><p>短期完成流水与发票确认；中期建立客户回款、采购发票和税负监控规则。</p></section>
"""
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{escape(str(enterprise.get("name", "企业")))} {escape(period)} 财务健康诊断</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; color: #172033; line-height: 1.6; }}
    h1, h2 {{ color: #1769E0; }}
    section {{ margin: 28px 0; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid #D9E2EF; padding: 8px 10px; text-align: left; }}
    .alert {{ border-left: 4px solid #C24136; background: #FFF4F2; padding: 10px 14px; }}
  </style>
</head>
<body>
  <h1>{escape(str(enterprise.get("name", "企业")))} {escape(period)} 财务健康诊断报告</h1>
{section_html}
</body>
</html>
"""


def _missing_data(*, statement: dict, tax_draft: dict) -> list[str]:
    missing = []
    balance = statement.get("estimated_balance_sheet", {})
    income = statement.get("estimated_income_statement", {})
    if not balance.get("total_assets") or not balance.get("total_liabilities"):
        missing.append("缺少资产负债表核心数据")
    if not income.get("revenue") or not income.get("operating_profit"):
        missing.append("缺少利润表核心数据")
    if not tax_draft.get("vat_payable"):
        missing.append("缺少税务申报草稿数据")
    return missing


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _percent(value: Decimal) -> str:
    return f"{(value * Decimal('100')).quantize(Decimal('0.01'))}%"


def _wan(value) -> str:
    return f"{(_decimal(value) / Decimal('10000')).quantize(Decimal('0.01'))}"
