from __future__ import annotations

from html import escape


def render_monthly_brief_html(
    *,
    enterprise_name: str,
    period: str,
    summary: dict,
    exceptions: list[dict] | None = None,
) -> str:
    exceptions = exceptions or []
    exception_rows = "".join(
        f"<tr><td>{escape(str(item.get('label', '异常事项')))}</td><td>{escape(str(item.get('count', 0)))}</td></tr>"
        for item in exceptions
    )
    if not exception_rows:
        exception_rows = "<tr><td>异常事项</td><td>0</td></tr>"

    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{escape(enterprise_name)} {escape(period)} 月度简报</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; color: #172033; }}
    section {{ margin: 24px 0; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #D9E2EF; padding: 8px 10px; text-align: left; }}
    h1, h2 {{ color: #1769E0; }}
  </style>
</head>
<body>
  <h1>{escape(enterprise_name)} {escape(period)} 月度经营简报</h1>
  <section>
    <h2>本月经营概览</h2>
    <p>营业收入：{_yuan(summary.get("revenue", 0))}；期间费用：{_yuan(summary.get("expense", 0))}。</p>
  </section>
  <section>
    <h2>税务概览</h2>
    <p>预计本期应纳增值税：{_yuan(summary.get("tax_payable", 0))}。</p>
  </section>
  <section>
    <h2>异常事项</h2>
    <table><tbody>{exception_rows}</tbody></table>
  </section>
  <section>
    <h2>现金流提醒</h2>
    <p>本期现金净变动：{_yuan(summary.get("cash_net", 0))}。</p>
  </section>
  <section>
    <h2>下月建议</h2>
    <p>优先处理未匹配流水和发票，确认纳税数据后再导出申报草稿。</p>
  </section>
</body>
</html>
"""


def _yuan(value) -> str:
    return f"{float(value):,.2f}元"
