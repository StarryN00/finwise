from __future__ import annotations

import base64
import os
import re
from pathlib import Path

from . import analyzer, chart_maker, kimi_writer, pdf_renderer


def generate_finhealth_report(
    financial_data: dict,
    output_dir: str = "output",
    kimi_api_key: str | None = None,
) -> str:
    """生成财务健康诊断报告 PDF,返回 PDF 绝对路径。"""
    if kimi_api_key:
        os.environ["MOONSHOT_API_KEY"] = kimi_api_key

    base_dir = Path(__file__).parent
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    metrics = analyzer.compute_all_metrics(financial_data)
    chart_dir = output_path / "charts"
    charts = chart_maker.make_all_charts(metrics, chart_dir)
    charts = {key: _image_data_uri(Path(value)) for key, value in charts.items()}
    texts = kimi_writer.generate_all_sections(metrics["kimi_context"])

    context = _build_template_context(financial_data, metrics, charts, texts)
    html = pdf_renderer.render_html(str(base_dir / "templates"), context)
    safe_company = _safe_filename(financial_data["company"]["name"])
    safe_date = _safe_filename(financial_data["company"]["report_date"])
    pdf_path = output_path / f"财务健康诊断报告_{safe_company}_{safe_date}.pdf"
    pdf_renderer.html_to_pdf(html, str(pdf_path), base_url=str(base_dir))
    return str(pdf_path.resolve())


def _build_template_context(data: dict, metrics: dict, charts: dict, texts: dict) -> dict:
    latest = metrics["latest_year"]
    previous = metrics["previous_year"]
    raw = metrics["statements"]["raw"]
    adjusted = metrics["statements"]["adjusted"]
    income = data["income_statement"]
    vat = data["vat_declaration"]
    latest_adjusted = adjusted[latest]
    latest_raw = raw[latest]
    latest_income = income[latest]
    total_assets = latest_adjusted["资产总计"] or 1
    risk_rows = [
        (("账务规范性", "应付账款负数金额"), _risk_display(metrics["risks"]["应付账款负数金额"], "万元")),
        (("资本结构", "资产负债率（调整后）"), _risk_display(metrics["risks"]["资产负债率"], "pct")),
        (("短期偿债", "现金比率"), _risk_display(metrics["risks"]["现金比率"], "pct")),
        (("盈利能力", "净利率"), _risk_display(metrics["risks"]["净利率"], "pct")),
        (("营运效率", "存货周转天数"), _risk_display(metrics["risks"]["存货周转天数"], "天")),
        (("税务合规", "增值税税负率"), _risk_display(metrics["risks"]["增值税税负率"], "pct")),
    ]
    balance_overview_rows = [
        {"name": "流动资产（调整后）", "amount": _wan(latest_adjusted["流动资产"]), "ratio": _pct(latest_adjusted["流动资产"] / total_assets)},
        {"name": "其中：货币资金", "amount": _wan(latest_raw["货币资金"]), "ratio": _pct(latest_raw["货币资金"] / total_assets)},
        {"name": "其中：应收账款", "amount": _wan(latest_raw["应收账款"]), "ratio": _pct(latest_raw["应收账款"] / total_assets)},
        {"name": "其中：存货", "amount": _wan(latest_raw["存货"]), "ratio": _pct(latest_raw["存货"] / total_assets)},
        {"name": "其中：预付性质款项（应付负数）", "amount": _wan(latest_adjusted["预付性质款项"]), "ratio": _pct(latest_adjusted["预付性质款项"] / total_assets)},
        {"name": "非流动资产", "amount": _wan(latest_raw.get("固定资产", 0)), "ratio": _pct(latest_raw.get("固定资产", 0) / total_assets)},
        {"name": "资产总计（调整后）", "amount": _wan(latest_adjusted["资产总计"]), "ratio": "100%"},
        {"name": "负债合计", "amount": _wan(latest_adjusted["负债合计"]), "ratio": "-"},
        {"name": "所有者权益", "amount": _wan(latest_adjusted["所有者权益"]), "ratio": "-"},
    ]
    return {
        "company": data["company"],
        "metrics": metrics,
        "texts": texts,
        "charts": charts,
        "latest": latest,
        "previous": previous,
        "latest_raw": latest_raw,
        "prev_raw": raw[previous],
        "latest_adjusted": latest_adjusted,
        "latest_income": latest_income,
        "prev_income": income[previous],
        "latest_vat": vat[latest],
        "prev_vat": vat[previous],
        "cap": metrics["capital_structure"][latest],
        "solv": metrics["short_term_solvency"][latest],
        "profit": metrics["profitability"][latest],
        "prev_profit": metrics["profitability"][previous],
        "eff": metrics["operating_efficiency"][latest],
        "prev_eff": metrics["operating_efficiency"][previous],
        "tax": metrics["tax"][latest],
        "prev_tax": metrics["tax"][previous],
        "risk_rows": risk_rows,
        "balance_overview_rows": balance_overview_rows,
    }


def _risk_display(risk: dict, unit: str) -> dict:
    value = risk["value"]
    if unit == "pct":
        display = _pct(value)
    elif unit == "万元":
        display = _wan(value)
    elif unit == "天":
        display = f"{value:.1f}天"
    else:
        display = str(value)
    tag_class = {"高风险": "tag-high", "中风险": "tag-mid", "低风险": "tag-low"}[risk["level"]]
    return {**risk, "display": display, "tag_class": tag_class}


def _wan(value) -> str:
    return f"{float(value or 0) / 10000:.2f}"


def _pct(value) -> str:
    return f"{float(value or 0) * 100:.2f}%"


def _safe_filename(value: str) -> str:
    return re.sub(r"[\\\\/:*?\"<>|\\s]+", "_", value).strip("_")


def _image_data_uri(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"
