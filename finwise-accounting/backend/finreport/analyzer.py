from __future__ import annotations

from copy import deepcopy


NEGATIVE_LIABILITY_FIELDS = ["应付账款", "其他应付款", "应付职工薪酬"]


def compute_all_metrics(data: dict) -> dict:
    balance = data.get("balance_sheet", {})
    income = data.get("income_statement", {})
    vat = data.get("vat_declaration", {})
    years = sorted(balance.keys())
    latest = years[-1]
    previous = years[-2] if len(years) >= 2 else latest
    adjusted = {year: _adjust_balance_sheet(values) for year, values in balance.items()}

    metrics = {
        "source": data,
        "company": data.get("company", {}),
        "years": years,
        "latest_year": latest,
        "previous_year": previous,
        "statements": {"raw": deepcopy(balance), "adjusted": adjusted},
        "capital_structure": {},
        "short_term_solvency": {},
        "profitability": {},
        "operating_efficiency": {},
        "tax": {},
    }
    for year in years:
        b = adjusted[year]
        raw_b = balance.get(year, {})
        inc = income.get(year, {})
        vat_year = vat.get(year, {})
        avg_equity = _avg(adjusted.get(previous if year == latest else year, b).get("所有者权益"), b.get("所有者权益"))
        avg_assets = _avg(adjusted.get(previous if year == latest else year, b).get("资产总计"), b.get("资产总计"))
        metrics["capital_structure"][year] = {
            "资产负债率": _ratio(b.get("负债合计"), b.get("资产总计")),
            "权益乘数": _ratio(b.get("资产总计"), b.get("所有者权益")),
            "净资产负债率": _ratio(b.get("负债合计"), b.get("所有者权益")),
        }
        metrics["short_term_solvency"][year] = {
            "流动比率": _ratio(b.get("流动资产"), b.get("流动负债")),
            "速动比率": _ratio(_num(b.get("流动资产")) - _num(raw_b.get("存货")), b.get("流动负债")),
            "现金比率": _ratio(raw_b.get("货币资金"), b.get("流动负债")),
        }
        metrics["profitability"][year] = {
            "毛利率": _ratio(_num(inc.get("营业收入")) - _num(inc.get("营业成本")), inc.get("营业收入")),
            "净利率": _ratio(inc.get("净利润"), inc.get("营业收入")),
            "管理费用率": _ratio(inc.get("管理费用"), inc.get("营业收入")),
            "财务费用率": _ratio(inc.get("财务费用"), inc.get("营业收入")),
            "营业利润率": _ratio(inc.get("营业利润"), inc.get("营业收入")),
            "ROE": _ratio(inc.get("净利润"), avg_equity),
            "ROA": _ratio(inc.get("净利润"), avg_assets),
        }
        prev_b = adjusted.get(previous if year == latest else year, b)
        avg_ar = _avg(prev_b.get("应收账款"), b.get("应收账款"))
        avg_inventory = _avg(prev_b.get("存货"), b.get("存货"))
        metrics["operating_efficiency"][year] = {
            "应收账款周转天数": 365 * avg_ar / _num(inc.get("营业收入")) if _num(inc.get("营业收入")) else 0,
            "存货周转天数": 365 * avg_inventory / _num(inc.get("营业成本")) if _num(inc.get("营业成本")) else 0,
        }
        metrics["tax"][year] = {
            "增值税税负率": _ratio(vat_year.get("应纳税额"), inc.get("营业收入")),
        }

    metrics["risks"] = _build_risks(metrics, balance, latest)
    metrics["potential_losses"] = calculate_potential_losses(balance.get(latest, {}), income, latest, previous)
    metrics["kimi_context"] = _build_kimi_context(data, metrics)
    return metrics


def calculate_potential_losses(latest_balance: dict, income: dict, latest: str = "2025", previous: str = "2024") -> list[dict]:
    payable_negative = abs(min(_num(latest_balance.get("应付账款")), 0))
    other_payable_negative = abs(min(_num(latest_balance.get("其他应付款")), 0))
    inventory = _num(latest_balance.get("存货"))
    short_loan = _num(latest_balance.get("短期借款"))
    avg_loss = abs((_num(income.get(previous, {}).get("净利润")) + _num(income.get(latest, {}).get("净利润"))) / 2)
    rows = [
        {"项目": "预付账款坏账风险(20%)", "金额": payable_negative * 0.2, "计算依据": "应付账款负数绝对值 x 20%"},
        {"项目": "其他应收款坏账风险(30%)", "金额": other_payable_negative * 0.3, "计算依据": "其他应付款负数绝对值 x 30%"},
        {"项目": "存货跌价损失(10%)", "金额": inventory * 0.1, "计算依据": "存货 x 10%"},
        {"项目": "短期借款违约罚息(年化10%)", "金额": short_loan * 0.1, "计算依据": "短期借款 x 10%"},
        {"项目": "下年度预计亏损", "金额": avg_loss, "计算依据": "近两年净利润均值绝对值"},
    ]
    rows.append({"项目": "合计", "金额": sum(row["金额"] for row in rows), "计算依据": "以上潜在损失合计"})
    return rows


def _adjust_balance_sheet(values: dict) -> dict:
    adjusted = deepcopy(values)
    negative_sum = sum(abs(_num(values.get(field))) for field in NEGATIVE_LIABILITY_FIELDS if _num(values.get(field)) < 0)
    liabilities_include_negative = _num(values.get("负债合计")) - negative_sum > 0
    adjusted["预付性质款项"] = negative_sum
    adjusted["负债合计"] = _num(values.get("负债合计")) - negative_sum if liabilities_include_negative else _num(values.get("负债合计"))
    adjusted["流动负债"] = _num(values.get("流动负债")) - negative_sum if liabilities_include_negative else _num(values.get("流动负债"))
    adjusted["流动资产"] = _num(values.get("流动资产")) + negative_sum if liabilities_include_negative else _num(values.get("流动资产"))
    adjusted["资产总计"] = _num(values.get("资产总计")) + negative_sum if liabilities_include_negative else _num(values.get("资产总计"))
    adjusted["所有者权益"] = _num(values.get("所有者权益"))
    return adjusted


def _build_risks(metrics: dict, balance: dict, latest: str) -> dict:
    raw_latest = balance.get(latest, {})
    payable_negative = min(_num(raw_latest.get("应付账款")), 0)
    risks = {
        "现金比率": _risk(metrics["short_term_solvency"][latest]["现金比率"], high=lambda x: x < 0.05, low=lambda x: x > 0.2, threshold=">20%"),
        "资产负债率": _risk(metrics["capital_structure"][latest]["资产负债率"], high=lambda x: x > 0.7, low=lambda x: x < 0.7, threshold="<70%"),
        "净利率": _risk(metrics["profitability"][latest]["净利率"], high=lambda x: x < 0, low=lambda x: x > 0.05, threshold=">5%"),
        "存货周转天数": _risk(metrics["operating_efficiency"][latest]["存货周转天数"], high=lambda x: x > 240, low=lambda x: x < 120, threshold="<120天"),
        "增值税税负率": _risk(metrics["tax"][latest]["增值税税负率"], high=lambda x: x < 0.02 or x > 0.06, low=lambda x: 0.03 <= x <= 0.05, threshold="3%-5%"),
        "应付账款负数金额": _risk(payable_negative, high=lambda x: x < 0, low=lambda x: x >= 0, threshold=">=0"),
    }
    return risks


def _risk(value: float, *, high, low, threshold: str) -> dict:
    if high(value):
        level = "高风险"
    elif low(value):
        level = "低风险"
    else:
        level = "中风险"
    return {"value": value, "level": level, "safe_threshold": threshold}


def _build_kimi_context(data: dict, metrics: dict) -> dict:
    latest = metrics["latest_year"]
    previous = metrics["previous_year"]
    raw = data["balance_sheet"][latest]
    income = data["income_statement"]
    latest_income = income[latest]
    prev_income = income[previous]
    adjusted = metrics["statements"]["adjusted"][latest]
    return {
        "应付账款负数": _wan(abs(min(_num(raw.get("应付账款")), 0))),
        "其他应付款负数": _wan(abs(min(_num(raw.get("其他应付款")), 0))),
        "货币资金": _wan(raw.get("货币资金")),
        "短期借款": _wan(raw.get("短期借款")),
        "现金比率": _pct(metrics["short_term_solvency"][latest]["现金比率"]),
        "近两年净利润": f"{_wan(prev_income.get('净利润'))}/{_wan(latest_income.get('净利润'))}",
        "累计未分配利润": _wan(raw.get("未分配利润")),
        "净利率": _pct(metrics["profitability"][latest]["净利率"]),
        "毛利率_2024": _pct(metrics["profitability"][previous]["毛利率"]),
        "毛利率_2025": _pct(metrics["profitability"][latest]["毛利率"]),
        "管理费用率": _pct(metrics["profitability"][latest]["管理费用率"]),
        "年利息支出": _wan(latest_income.get("利息支出")),
        "应纳税所得额": _wan(latest_income.get("净利润")),
        "资产总额": _wan(adjusted.get("资产总计")),
        "标准税率_25": "25%",
        "小微税率_5": "5%",
        "资产负债率": _pct(metrics["capital_structure"][latest]["资产负债率"]),
        "流动比率": f"{metrics['short_term_solvency'][latest]['流动比率']:.2f}",
        "速动比率": f"{metrics['short_term_solvency'][latest]['速动比率']:.2f}",
        "应付账款负数": _wan(abs(min(_num(raw.get("应付账款")), 0))),
        "存货周转天数": f"{metrics['operating_efficiency'][latest]['存货周转天数']:.1f}天",
        "研究费用": _wan(latest_income.get("研究费用")),
        "加计金额": _wan(latest_income.get("研究费用")),
        "当期是否盈利": "亏损" if _num(latest_income.get("净利润")) < 0 else "盈利",
        "应收账款_2024": _wan(data["balance_sheet"][previous].get("应收账款")),
        "应收账款_2025": _wan(raw.get("应收账款")),
        "应收账款周转天数_2024": f"{metrics['operating_efficiency'][previous]['应收账款周转天数']:.1f}天",
        "应收账款周转天数_2025": f"{metrics['operating_efficiency'][latest]['应收账款周转天数']:.1f}天",
        "存货": _wan(raw.get("存货")),
        "库存商品": "未披露",
        "原材料": "未披露",
        "实收资本变动": _wan(_num(raw.get("实收资本")) - _num(data["balance_sheet"][previous].get("实收资本"))),
        "应收账款周转改善": f"{metrics['operating_efficiency'][previous]['应收账款周转天数'] - metrics['operating_efficiency'][latest]['应收账款周转天数']:.1f}天",
        "增值税税负率": _pct(metrics["tax"][latest]["增值税税负率"]),
    }


def _ratio(numerator, denominator) -> float:
    denominator_value = _num(denominator)
    if denominator_value == 0:
        return 0
    return _num(numerator) / denominator_value


def _avg(left, right) -> float:
    return (_num(left) + _num(right)) / 2


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _wan(value) -> str:
    return f"{_num(value) / 10000:.2f}万元"


def _pct(value) -> str:
    return f"{float(value) * 100:.2f}%"
