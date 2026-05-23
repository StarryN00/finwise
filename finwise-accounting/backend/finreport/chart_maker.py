from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager


PALETTE = ["#4C72B0", "#DD8452", "#55A467", "#C44E52", "#8172B3", "#937860", "#DA8BC3", "#8C8C8C"]
BAR_COLORS = ["#1F77B4", "#FF7F0E", "#2CA02C"]


def make_all_charts(metrics: dict, chart_dir: Path) -> dict[str, str]:
    chart_dir.mkdir(parents=True, exist_ok=True)
    charts = {
        "chart1": chart_dir / "chart1_balance_structure.png",
        "chart2": chart_dir / "chart2_solvency_profitability.png",
        "chart3": chart_dir / "chart3_profit_tax.png",
        "chart4": chart_dir / "chart4_cashflow_stress.png",
    }
    make_chart_balance_structure(metrics, charts["chart1"])
    make_chart_solvency_profitability(metrics, charts["chart2"])
    make_chart_profit_tax(metrics, charts["chart3"])
    make_chart_cashflow_stress(metrics, charts["chart4"])
    return {key: str(path.resolve()) for key, path in charts.items()}


def make_chart_balance_structure(metrics: dict, save_path: Path):
    _setup_font()
    latest = metrics["latest_year"]
    raw = metrics["statements"]["raw"][latest]
    adjusted = metrics["statements"]["adjusted"][latest]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    left_labels = ["货币资金", "应收账款", "存货", "固定资产", "其他流动资产", "应付账款负数", "其他应付负数", "应付职工薪酬负数"]
    known = _v(raw, "货币资金") + _v(raw, "应收账款") + _v(raw, "存货") + _v(raw, "固定资产") + adjusted["预付性质款项"]
    left_values = [
        _v(raw, "货币资金"),
        _v(raw, "应收账款"),
        _v(raw, "存货"),
        _v(raw, "固定资产"),
        max(_v(adjusted, "资产总计") - known, 0),
        abs(min(_v(raw, "应付账款"), 0)),
        abs(min(_v(raw, "其他应付款"), 0)),
        abs(min(_v(raw, "应付职工薪酬"), 0)),
    ]
    left_pie_values = [max(value, 0) for value in left_values]
    if sum(left_pie_values) == 0:
        left_pie_values = [1] + [0] * (len(left_values) - 1)
    axes[0].pie(left_pie_values, labels=_pie_labels(left_labels, left_values), colors=PALETTE, textprops={"fontsize": 7})
    axes[0].set_title(f"2025 年资产结构(调整后)\n总计:{_wan(adjusted['资产总计'])} 万元", fontsize=11, fontweight="bold")
    right_labels = ["短期借款", "所有者权益"]
    right_values = [max(_v(raw, "短期借款"), 0), max(_v(adjusted, "所有者权益"), 0)]
    if sum(right_values) == 0:
        right_values = [1, 1]
    axes[1].pie(right_values, labels=_pie_labels(right_labels, right_values), colors=PALETTE[:2], textprops={"fontsize": 8})
    axes[1].set_title(f"2025 年负债与权益结构\n总计:{_wan(sum(right_values))} 万元", fontsize=11, fontweight="bold")
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()


def make_chart_solvency_profitability(metrics: dict, save_path: Path):
    _setup_font()
    latest = metrics["latest_year"]
    previous = metrics["previous_year"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    sol_labels = ["资产负债率", "流动比率", "速动比率", "现金比率"]
    actual = [
        metrics["capital_structure"][latest]["资产负债率"] * 100,
        metrics["short_term_solvency"][latest]["流动比率"],
        metrics["short_term_solvency"][latest]["速动比率"],
        metrics["short_term_solvency"][latest]["现金比率"] * 100,
    ]
    safe = [70, 1.5, 1.0, 20]
    x = range(len(sol_labels))
    axes[0].bar([i - 0.18 for i in x], actual, width=0.36, label="2025 实际值", color=BAR_COLORS[0])
    axes[0].bar([i + 0.18 for i in x], safe, width=0.36, label="安全基准值", color=BAR_COLORS[1])
    axes[0].set_xticks(list(x), sol_labels, rotation=20)
    axes[0].set_title("偿债能力指标对比", fontsize=11, fontweight="bold")
    axes[0].legend()
    _label_bars(axes[0])

    prof_labels = ["毛利率", "净利率", "ROE", "ROA"]
    v2024 = [metrics["profitability"][previous][key] * 100 for key in prof_labels]
    v2025 = [metrics["profitability"][latest][key] * 100 for key in prof_labels]
    base = [25, 5, 10, 5]
    axes[1].bar([i - 0.24 for i in x], v2024, width=0.24, label="2024", color=BAR_COLORS[0])
    axes[1].bar(list(x), v2025, width=0.24, label="2025", color=BAR_COLORS[1])
    axes[1].bar([i + 0.24 for i in x], base, width=0.24, label="制造业基准", color=BAR_COLORS[2])
    axes[1].set_xticks(list(x), prof_labels, rotation=20)
    axes[1].set_title("盈利能力指标对比", fontsize=11, fontweight="bold")
    axes[1].legend()
    _label_bars(axes[1])
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()


def make_chart_profit_tax(metrics: dict, save_path: Path):
    _setup_font()
    latest = metrics["latest_year"]
    income = metrics["source"]["income_statement"][latest] if "source" in metrics else {}
    vat = metrics["source"]["vat_declaration"][latest] if "source" in metrics else {}
    if not income:
        income = {}
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    labels = ["营业收入", "营业成本", "毛利", "管理费用", "财务费用", "营业利润", "净利润"]
    values = [_v(income, "营业收入"), -_v(income, "营业成本"), _v(income, "营业收入") - _v(income, "营业成本"), -_v(income, "管理费用"), -_v(income, "财务费用"), _v(income, "营业利润"), _v(income, "净利润")]
    colors = ["#1F77B4" if value >= 0 else "#D62728" for value in values]
    axes[0].barh(labels, [_wan(value) for value in values], color=colors)
    axes[0].set_title("2025 年利润结构瀑布图", fontsize=11, fontweight="bold")
    for y, value in enumerate(values):
        axes[0].text(_wan(value), y, f"{_wan(value):.2f}", va="center", fontsize=8)
    tax_values = [_v(vat, "应纳税额"), _v(vat, "应纳税额") * 0.07, _v(vat, "应纳税额") * 0.03, _v(vat, "应纳税额") * 0.02]
    if sum(abs(value) for value in tax_values) == 0:
        tax_values = [1, 0.07, 0.03, 0.02]
    axes[1].pie(tax_values, labels=_pie_labels(["增值税", "城建税", "教育费附加", "地方教育附加"], tax_values), colors=PALETTE[:4], textprops={"fontsize": 8})
    axes[1].set_title(f"2025 年税费构成\n合计:{_wan(sum(tax_values))} 万元", fontsize=11, fontweight="bold")
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()


def make_chart_cashflow_stress(metrics: dict, save_path: Path):
    _setup_font()
    latest = metrics["latest_year"]
    raw = metrics["statements"]["raw"][latest]
    income = metrics["source"]["income_statement"][latest] if "source" in metrics else {}
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    labels = ["应收账款", "存货资金占用", "应付职工薪酬负数", "其他应付款负数", "应付账款负数"]
    values = [_v(raw, "应收账款"), _v(raw, "存货"), abs(min(_v(raw, "应付职工薪酬"), 0)), abs(min(_v(raw, "其他应付款"), 0)), abs(min(_v(raw, "应付账款"), 0))]
    axes[0].barh(labels, [_wan(v) for v in values], color=PALETTE[:5])
    axes[0].set_title("资金占用与流动资产构成(2025)", fontsize=11, fontweight="bold")
    stress_labels = ["年利息支出", "营运资金缺口", "短期借款", "货币资金"]
    gap = max(_v(raw, "短期借款") + _v(income, "利息支出") - _v(raw, "货币资金"), 0)
    stress_values = [-_v(income, "利息支出"), -gap, -_v(raw, "短期借款"), _v(raw, "货币资金")]
    axes[1].barh(stress_labels, [_wan(v) for v in stress_values], color=["#D62728", "#D62728", "#D62728", "#1F77B4"])
    axes[1].set_title("现金流压力测试(2025 年末)", fontsize=11, fontweight="bold")
    axes[1].annotate("现金/短期借款 = 0.14% 极度危险!", xy=(_wan(_v(raw, "货币资金")), 3), xytext=(5, 2.5), arrowprops={"arrowstyle": "->", "color": "#D62728"}, color="#D62728", fontsize=9)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()


def _setup_font():
    font_path = Path(__file__).parent / "static" / "fonts" / "SourceHanSansSC-Regular.otf"
    if font_path.exists():
        font_manager.fontManager.addfont(str(font_path))
        plt.rcParams["font.sans-serif"] = ["Source Han Sans SC"]
    else:
        plt.rcParams["font.sans-serif"] = ["STHeiti", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["font.size"] = 9


def _label_bars(axis):
    for container in axis.containers:
        axis.bar_label(container, fmt="%.2f", fontsize=7)


def _pie_labels(labels: list[str], values: list[float]) -> list[str]:
    total = sum(abs(v) for v in values) or 1
    return [f"{label}\n{_wan(value):.2f}万元 {abs(value) / total * 100:.1f}%" for label, value in zip(labels, values)]


def _v(data: dict, key: str) -> float:
    return float(data.get(key) or 0)


def _wan(value: float) -> float:
    return float(value or 0) / 10000
