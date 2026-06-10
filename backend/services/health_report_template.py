"""
Template-driven financial health report assembly.

The Phase 1 report follows the supplied 8-section framework. Metrics that need
balance sheets or income statements are surfaced as data gaps instead of being
invented from bank statements.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from backend.storage.manager import bank_transaction_store, enterprise_store, health_report_store, invoice_store


def build_data_completeness(enterprise_id: str, period_year: int, period_month: int) -> dict[str, Any]:
    enterprise = enterprise_store.get_by_id(enterprise_id)
    if not enterprise:
        return {}

    invoices = _period_invoices(enterprise_id, period_year, period_month)
    transactions = _period_transactions(enterprise_id, period_year, period_month)
    sales = [
        inv for inv in invoices
        if (inv.get("direction") or inv.get("invoice_type")) in {"SALES", "OUTPUT"}
        and inv.get("invoice_status") != "VOID"
    ]
    purchases = [
        inv for inv in invoices
        if (inv.get("direction") or inv.get("invoice_type")) in {"PURCHASE", "INPUT"}
        and inv.get("invoice_status") != "VOID"
    ]

    items = [
        {"key": "enterprise", "label": "企业基础信息", "status": "READY", "count": 1, "message": "已建立企业档案"},
        {
            "key": "bank_statement",
            "label": "银行流水",
            "status": "READY" if transactions else "MISSING",
            "count": len(transactions),
            "message": "可用于现金流分析" if transactions else "缺少本月银行流水",
        },
        {
            "key": "sales_invoices",
            "label": "销项明细",
            "status": "READY" if sales else "MISSING",
            "count": len(sales),
            "message": "可用于收入与销项税分析" if sales else "缺少电子税务局销项明细",
        },
        {
            "key": "purchase_invoices",
            "label": "进项明细",
            "status": "READY" if purchases else "MISSING",
            "count": len(purchases),
            "message": "可用于采购与进项抵扣分析" if purchases else "缺少电子税务局进项明细",
        },
        {
            "key": "financial_statements",
            "label": "资产负债表/利润表",
            "status": "MISSING",
            "count": 0,
            "message": "偿债、盈利和运营效率完整指标需补充财报数据",
        },
    ]
    ready = sum(1 for item in items if item["status"] == "READY")
    return {
        "enterprise_id": enterprise_id,
        "enterprise_name": enterprise.get("name"),
        "period_year": period_year,
        "period_month": period_month,
        "ready_count": ready,
        "total_count": len(items),
        "completion_rate": round(ready / len(items) * 100),
        "items": items,
    }


def build_financial_health_report(enterprise_id: str, period_year: int, period_month: int) -> dict[str, Any]:
    enterprise = enterprise_store.get_by_id(enterprise_id)
    if not enterprise:
        raise ValueError("Enterprise not found")

    invoices = _period_invoices(enterprise_id, period_year, period_month)
    transactions = _period_transactions(enterprise_id, period_year, period_month)
    sales = [
        inv for inv in invoices
        if (inv.get("direction") or inv.get("invoice_type")) in {"SALES", "OUTPUT"}
        and inv.get("invoice_status") != "VOID"
    ]
    purchases = [
        inv for inv in invoices
        if (inv.get("direction") or inv.get("invoice_type")) in {"PURCHASE", "INPUT"}
        and inv.get("invoice_status") != "VOID"
    ]

    sales_amount = _sum_decimal(sales, "amount")
    sales_tax = _sum_decimal(sales, "tax_amount")
    purchase_amount = _sum_decimal(purchases, "amount")
    purchase_tax = _sum_decimal(purchases, "tax_amount")
    vat_payable = max(sales_tax - purchase_tax, Decimal("0"))
    cash_inflow = _sum_decimal(transactions, "credit_amount")
    cash_outflow = _sum_decimal(transactions, "debit_amount")
    net_cash_flow = cash_inflow - cash_outflow
    vat_burden_rate = (vat_payable / sales_amount * Decimal("100")) if sales_amount > 0 else None

    missing_metrics = [
        "资产总额", "负债总额", "所有者权益", "流动资产", "流动负债", "存货",
        "货币资金", "营业成本", "净利润", "应收账款", "应付账款", "暂估应付",
    ]
    risks = _build_risks(invoices, transactions, net_cash_flow, vat_burden_rate)
    completeness = build_data_completeness(enterprise_id, period_year, period_month)
    score = _score_from_data(completeness, net_cash_flow, vat_burden_rate)
    report_id = f"FH-{period_year}{period_month:02d}-{enterprise_id}"

    return {
        "id": report_id,
        "report_id": report_id,
        "report_number": report_id,
        "report_type": "HEALTH_ANALYSIS",
        "enterprise_id": enterprise_id,
        "enterprise_name": enterprise.get("name"),
        "period_year": period_year,
        "period_month": period_month,
        "analysis_date": date.today().isoformat(),
        "overall_score": score,
        "overall_grade": _grade(score),
        "financing_score": max(0, min(100, score - 5)),
        "dimensions": {
            "profitability": 45 if sales_amount else 25,
            "solvency": 35,
            "operation_efficiency": 45 if transactions else 25,
            "growth": 35,
            "cash_flow": 75 if net_cash_flow > 0 else 45 if transactions else 25,
        },
        "data_completeness": completeness,
        "key_metrics": {
            "sales_amount": _money(sales_amount),
            "purchase_amount": _money(purchase_amount),
            "output_tax": _money(sales_tax),
            "input_tax": _money(purchase_tax),
            "vat_payable": _money(vat_payable),
            "vat_burden_rate": float(vat_burden_rate.quantize(Decimal("0.01"))) if vat_burden_rate is not None else None,
            "cash_inflow": _money(cash_inflow),
            "cash_outflow": _money(cash_outflow),
            "net_cash_flow": _money(net_cash_flow),
            "transaction_count": len(transactions),
            "sales_invoice_count": len(sales),
            "purchase_invoice_count": len(purchases),
        },
        "missing_metrics": missing_metrics,
        "risk_alerts": [risk["description"] for risk in risks],
        "improvement_suggestions": _build_suggestions(completeness, risks),
        "sections": _build_sections(enterprise, risks, missing_metrics, vat_burden_rate),
        "status": "COMPLETED",
    }


def save_financial_health_report(report: dict[str, Any]) -> dict[str, Any]:
    existing = health_report_store.first(
        enterprise_id=report["enterprise_id"],
        report_type="HEALTH_ANALYSIS",
        period_year=report["period_year"],
        period_month=report["period_month"],
    )
    if existing:
        return health_report_store.update(existing["id"], **report)
    return health_report_store.create(**report)


def _period_invoices(enterprise_id: str, year: int, month: int) -> list[dict]:
    prefix = f"{year:04d}-{month:02d}"
    return [
        inv for inv in invoice_store.filter(enterprise_id=enterprise_id)
        if str(inv.get("issue_date", "")).startswith(prefix)
    ]


def _period_transactions(enterprise_id: str, year: int, month: int) -> list[dict]:
    prefix = f"{year:04d}-{month:02d}"
    return [
        tx for tx in bank_transaction_store.filter(enterprise_id=enterprise_id)
        if str(tx.get("transaction_date", "")).startswith(prefix) and tx.get("status") != "DELETED"
    ]


def _sum_decimal(rows: list[dict], field: str) -> Decimal:
    return sum((Decimal(str(row.get(field) or 0)) for row in rows), Decimal("0"))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _score_from_data(completeness: dict, net_cash_flow: Decimal, vat_burden_rate: Decimal | None) -> int:
    score = 45 + completeness.get("ready_count", 0) * 8
    if net_cash_flow > 0:
        score += 8
    elif net_cash_flow < 0:
        score -= 8
    if vat_burden_rate is not None and vat_burden_rate > Decimal("8"):
        score -= 8
    return max(0, min(100, score))


def _grade(score: int) -> str:
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def _build_risks(invoices: list[dict], transactions: list[dict], net_cash_flow: Decimal, vat_burden_rate: Decimal | None) -> list[dict]:
    risks: list[dict] = []
    if not invoices:
        risks.append({"level": "高风险", "description": "本月缺少进销项明细，税负与收入分析可信度不足", "amount": None})
    if not transactions:
        risks.append({"level": "高风险", "description": "本月缺少银行流水，现金流压力无法验证", "amount": None})
    if transactions and net_cash_flow < 0:
        risks.append({"level": "中风险", "description": "本月经营净现金流为负，需关注回款与支出节奏", "amount": _money(abs(net_cash_flow))})
    if vat_burden_rate is not None and vat_burden_rate > Decimal("5"):
        risks.append({"level": "中风险", "description": "增值税税负率高于制造业 3%-5% 常见区间", "amount": float(vat_burden_rate)})
    risks.append({"level": "数据不足", "description": "缺少资产负债表/利润表，偿债能力和盈利能力完整指标待补充", "amount": None})
    return risks[:5]


def _build_suggestions(completeness: dict, risks: list[dict]) -> list[str]:
    missing = {item["key"] for item in completeness.get("items", []) if item["status"] == "MISSING"}
    suggestions = []
    if "sales_invoices" in missing or "purchase_invoices" in missing:
        suggestions.append("先补齐电子税务局进销项明细，形成税负和收入采购的分析基础")
    if "financial_statements" in missing:
        suggestions.append("补充资产负债表和利润表后，再生成完整版偿债与盈利能力分析")
    if any("净现金流为负" in risk["description"] for risk in risks):
        suggestions.append("优先核查大额支出与回款计划，必要时建立月度现金流预算")
    suggestions.append("每月固定按企业、流水、进项、销项顺序导入，生成报告前先检查数据完整性")
    return suggestions


def _build_sections(enterprise: dict, risks: list[dict], missing_metrics: list[str], vat_burden_rate: Decimal | None) -> list[dict]:
    return [
        {"title": "一、报告摘要与核心结论", "summary": "列示 TOP 风险、风险等级矩阵和本期可计算结论。", "items": risks},
        {"title": "二、企业概况与财务概览", "summary": "展示企业名称、税号、行业、地区、纳税人资格和小微企业判定所需数据状态。"},
        {"title": "三、偿债能力分析", "summary": "资产负债率、流动比率、速动比率、现金比率等需财报支持，本期标记为数据不足。"},
        {"title": "四、盈利能力分析", "summary": "收入与采购可由进销项明细辅助判断，毛利、净利、ROE 需利润表支持。"},
        {"title": "五、运营效率与现金流分析", "summary": "现金流可由银行流水计算，应收账款周转和应付暂估需财报/明细账补充。"},
        {"title": "六、税务风险分析", "summary": f"增值税税负率：{vat_burden_rate.quantize(Decimal('0.01')) if vat_burden_rate is not None else '待补充'}%。"},
        {"title": "七、主要财务风险与代价", "summary": "潜在损失测算需要暂估应付、应收账款和所得税数据；缺失项不会虚构。"},
        {"title": "八、改进建议与应对措施", "summary": "短期先补齐月度数据并控制现金流，中长期补充财报后完善诊断。"},
    ]
