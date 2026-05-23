from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.pdfmetrics import registerFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


registerFont(UnicodeCIDFont("STSong-Light"))

PAGE_WIDTH, PAGE_HEIGHT = A4
BLUE = colors.HexColor("#17345D")
BLUE_2 = colors.HexColor("#285F97")
LIGHT_BLUE = colors.HexColor("#EAF2FB")
TEXT = colors.HexColor("#172033")
MUTED = colors.HexColor("#52647D")
GRID = colors.HexColor("#D9E2EF")
RISK_RED = colors.HexColor("#B42318")
RISK_ORANGE = colors.HexColor("#B54708")
RISK_GREEN = colors.HexColor("#027A48")


def render_health_report_pdf(
    *,
    output_path: Path,
    enterprise: dict,
    period: str,
    statement: dict,
    tax_draft: dict,
    sections: list[dict] | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()
    balance = statement.get("estimated_balance_sheet", {})
    income = statement.get("estimated_income_statement", {})
    ai_sections = _normalize_sections(sections or [])
    compiled_date = date.today().strftime("%Y 年 %m 月 %d 日")
    story: list = []

    story.extend(_cover_story(styles, enterprise=enterprise, period=period, compiled_date=compiled_date))
    story.append(PageBreak())

    story.extend(_heading(styles, "一、报告摘要与核心结论"))
    story.append(Paragraph("本章为报告开篇，概括企业财务状况的核心问题，帮助经营者快速识别主要风险点。", styles["body"]))
    story.extend(_paragraphs(styles, _find_section(ai_sections, "摘要", _core_findings(balance, income, tax_draft))))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("1.2 风险等级总览矩阵", styles["h3"]))
    story.append(_table(_risk_overview_rows(balance, income, tax_draft), col_widths=[34 * mm, 42 * mm, 32 * mm, 30 * mm, 46 * mm]))
    story.append(PageBreak())

    story.extend(_heading(styles, "二、企业概况与财务概览"))
    story.append(Paragraph("2.1 企业基本信息", styles["h3"]))
    story.append(_table(_enterprise_rows(enterprise, period), col_widths=[38 * mm, 132 * mm]))
    story.append(Paragraph("2.2 小型微利企业政策适用性分析", styles["h3"]))
    story.append(
        Paragraph(
            "根据财政部、税务总局关于小型微利企业所得税优惠政策的要求，企业需同时满足行业、人数、资产和应纳税所得额条件。",
            styles["body"],
        )
    )
    story.append(_table(_small_business_rows(enterprise, balance, income), col_widths=[16 * mm, 44 * mm, 44 * mm, 48 * mm, 22 * mm]))
    story.append(Paragraph("2.3 资产负债总体规模", styles["h3"]))
    story.append(_table(_scale_rows(balance, income), col_widths=[42 * mm, 42 * mm, 42 * mm, 42 * mm]))
    story.append(PageBreak())

    story.extend(_heading(styles, "三、偿债能力分析"))
    story.append(Paragraph("3.1 资产负债率分析", styles["h3"]))
    story.append(_table(_solvency_rows(balance), col_widths=[34 * mm, 44 * mm, 32 * mm, 34 * mm, 34 * mm]))
    story.append(Paragraph("3.2 短期偿债能力分析", styles["h3"]))
    story.extend(_paragraphs(styles, _find_section(ai_sections, "偿债", ["资产负债结构、现金余额和应付账款规模共同决定短期偿债压力，应结合债务到期日持续滚动测算。"])))
    story.append(PageBreak())

    story.extend(_heading(styles, "四、盈利能力分析"))
    story.append(Paragraph("4.1 利润率分析", styles["h3"]))
    story.append(_table(_profit_rows(income), col_widths=[36 * mm, 40 * mm, 34 * mm, 34 * mm, 34 * mm]))
    story.append(Paragraph("4.2 费用结构分析", styles["h3"]))
    story.extend(_paragraphs(styles, _find_section(ai_sections, "盈利", ["盈利能力应重点关注毛利率、期间费用率和项目成本归集，必要时按订单维度建立毛利复核。"])))
    story.append(PageBreak())

    story.extend(_heading(styles, "五、运营效率与现金流分析"))
    story.append(Paragraph("5.1 应收账款回收风险", styles["h3"]))
    story.append(_table(_working_capital_rows(balance, income), col_widths=[44 * mm, 42 * mm, 88 * mm]))
    story.append(Paragraph("5.2 应付账款暂估问题", styles["h3"]))
    story.append(Paragraph("暂估应付会影响成本费用真实性、进项抵扣和企业所得税测算，应在月度结账前完成发票补齐和往来核对。", styles["body"]))
    story.append(Paragraph("5.3 现金流压力评估", styles["h3"]))
    story.extend(_paragraphs(styles, _find_section(ai_sections, "现金", ["现金流压力需要通过回款计划、付款排期和库存压降共同改善。"])))
    story.append(PageBreak())

    story.extend(_heading(styles, "六、税务风险分析"))
    story.append(Paragraph("6.1 税负水平评估", styles["h3"]))
    story.append(_table(_tax_rows(tax_draft), col_widths=[46 * mm, 42 * mm, 88 * mm]))
    story.append(Paragraph("6.2 增值税税负分析", styles["h3"]))
    story.extend(_paragraphs(styles, _find_section(ai_sections, "税务", ["需核对发票匹配、进项抵扣和申报草稿口径，确保账、票、税一致。"])))
    story.append(PageBreak())

    story.extend(_heading(styles, "七、主要财务风险与代价"))
    story.append(Paragraph("7.1 高风险事项清单", styles["h3"]))
    story.append(_table(_risk_cost_rows(balance, income, tax_draft), col_widths=[50 * mm, 38 * mm, 84 * mm]))
    story.append(Paragraph("7.2 风险代价量化", styles["h3"]))
    story.append(Paragraph("风险代价需按实际账龄、合同、发票补缴情形继续细化，当前结果作为经营者优先级排序依据。", styles["body"]))
    story.append(PageBreak())

    story.extend(_heading(styles, "八、改进建议与应对措施"))
    story.append(Paragraph("8.1 短期应对措施（1-3个月）", styles["h3"]))
    story.extend(_bullets(styles, ["完成未匹配发票、流水和往来款复核。", "建立重点客户回款清单和供应商付款排期。", "对异常暂估、负数往来和高额费用进行专项清理。"]))
    story.append(Paragraph("8.2 中长期优化方向（3-12个月）", styles["h3"]))
    story.extend(_paragraphs(styles, _find_section(ai_sections, "建议", ["建立项目毛利核算、税负监控和月度经营复盘机制，持续优化资本结构和现金流质量。"])))
    story.append(PageBreak())

    story.extend(_heading(styles, "附录：财务指标速查表"))
    story.append(_table(_appendix_rows(), col_widths=[44 * mm, 42 * mm, 42 * mm, 42 * mm]))

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=f"{enterprise.get('name', '企业')} {period} 财务健康诊断报告",
        author="智税管家",
    )
    doc.build(story, onFirstPage=_draw_cover_background, onLaterPages=_draw_page_header)
    return output_path


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_en": ParagraphStyle("cover_en", parent=base["Normal"], fontName="STSong-Light", fontSize=25, leading=32, textColor=colors.white, alignment=TA_CENTER, spaceAfter=18),
        "cover_title": ParagraphStyle("cover_title", parent=base["Normal"], fontName="STSong-Light", fontSize=31, leading=40, textColor=colors.white, alignment=TA_CENTER, spaceAfter=14),
        "cover_subtitle": ParagraphStyle("cover_subtitle", parent=base["Normal"], fontName="STSong-Light", fontSize=13, leading=21, textColor=colors.HexColor("#DBEAFE"), alignment=TA_CENTER, spaceAfter=32),
        "cover_meta": ParagraphStyle("cover_meta", parent=base["Normal"], fontName="STSong-Light", fontSize=12, leading=22, textColor=colors.white, alignment=TA_LEFT),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="STSong-Light", fontSize=18, leading=24, textColor=BLUE, spaceAfter=10),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontName="STSong-Light", fontSize=12.5, leading=18, textColor=BLUE_2, spaceBefore=8, spaceAfter=6),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="STSong-Light", fontSize=10.5, leading=17, textColor=TEXT, spaceAfter=6),
        "bullet": ParagraphStyle("bullet", parent=base["BodyText"], fontName="STSong-Light", fontSize=10.5, leading=17, leftIndent=10, firstLineIndent=-10, textColor=TEXT, spaceAfter=4),
        "cell": ParagraphStyle("cell", parent=base["BodyText"], fontName="STSong-Light", fontSize=8.8, leading=12, textColor=TEXT),
        "cell_head": ParagraphStyle("cell_head", parent=base["BodyText"], fontName="STSong-Light", fontSize=9, leading=12, textColor=colors.HexColor("#41516A")),
    }


def _cover_story(styles: dict[str, ParagraphStyle], *, enterprise: dict, period: str, compiled_date: str) -> list:
    industry = enterprise.get("industry") or "未填写"
    meta_rows = [
        ("诊断对象", str(enterprise.get("name") or "未命名企业")),
        ("所属行业", str(industry)),
        ("纳税人状态", _taxpayer_label(enterprise.get("taxpayer_type"))),
        ("报告期间", period),
        ("编制日期", compiled_date),
    ]
    meta = "<br/>".join(f"{label}：{value}" for label, value in meta_rows)
    return [
        Spacer(1, 95 * mm),
        Paragraph("FINANCIAL HEALTH DIAGNOSTIC", styles["cover_en"]),
        Paragraph("企业财务健康诊断报告", styles["cover_title"]),
        Paragraph("基于资产负债表、利润表及增值税申报表的多维度财务风险分析与量化评估", styles["cover_subtitle"]),
        Table([[Paragraph(meta, styles["cover_meta"])]], colWidths=[135 * mm], style=TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.7, colors.Color(1, 1, 1, alpha=0.38)), ("TOPPADDING", (0, 0), (-1, -1), 12), ("LEFTPADDING", (0, 0), (-1, -1), 0)])),
    ]


def _heading(styles: dict[str, ParagraphStyle], title: str) -> list:
    return [Paragraph(title, styles["h2"])]


def _paragraphs(styles: dict[str, ParagraphStyle], paragraphs: list[str]) -> list:
    return [Paragraph(str(item), styles["body"]) for item in paragraphs if str(item).strip()]


def _bullets(styles: dict[str, ParagraphStyle], items: list[str]) -> list:
    return [Paragraph(f"- {item}", styles["bullet"]) for item in items]


def _table(rows: list[list[object]], *, col_widths: list[float]) -> Table:
    styles = _styles()
    wrapped_rows = []
    for row_index, row in enumerate(rows):
        style_name = "cell_head" if row_index == 0 else "cell"
        wrapped_rows.append([Paragraph(str(cell), styles[style_name]) for cell in row])
    table = Table(wrapped_rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("GRID", (0, 0), (-1, -1), 0.5, GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _draw_cover_background(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BLUE)
    canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)
    canvas.setFillColor(BLUE_2)
    canvas.rect(PAGE_WIDTH * 0.58, 0, PAGE_WIDTH * 0.42, PAGE_HEIGHT, stroke=0, fill=1)
    canvas.setFillColor(colors.Color(1, 1, 1, alpha=0.08))
    canvas.circle(PAGE_WIDTH - 42 * mm, PAGE_HEIGHT - 50 * mm, 48 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.Color(1, 1, 1, alpha=0.08))
    canvas.rect(0, PAGE_HEIGHT - 16 * mm, PAGE_WIDTH, 16 * mm, stroke=0, fill=1)
    canvas.restoreState()


def _draw_page_header(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BLUE)
    canvas.rect(0, PAGE_HEIGHT - 6 * mm, PAGE_WIDTH, 6 * mm, stroke=0, fill=1)
    canvas.setFont("STSong-Light", 8.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, PAGE_HEIGHT - 12 * mm, "企业财务健康诊断报告")
    canvas.drawRightString(PAGE_WIDTH - 18 * mm, 10 * mm, str(canvas.getPageNumber()))
    canvas.restoreState()


def _normalize_sections(sections: list[dict]) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for section in sections:
        title = str(section.get("title") or "").strip()
        content = section.get("content") or []
        if isinstance(content, str):
            content = [content]
        if title:
            normalized[title] = [str(item).strip() for item in content if str(item).strip()]
    return normalized


def _find_section(sections: dict[str, list[str]], keyword: str, fallback: list[str]) -> list[str]:
    for title, content in sections.items():
        if keyword in title and content:
            return content
    return fallback


def _enterprise_rows(enterprise: dict, period: str) -> list[list[str]]:
    return [
        ["项目", "内容"],
        ["企业名称", str(enterprise.get("name") or "未命名企业")],
        ["统一社会信用代码", str(enterprise.get("unified_social_credit_code") or "未填写")],
        ["所属行业", str(enterprise.get("industry") or "未填写")],
        ["注册地址", str(enterprise.get("registered_address") or "未填写")],
        ["法定代表人", str(enterprise.get("legal_representative") or "未填写")],
        ["企业类型", str(enterprise.get("enterprise_type") or "有限责任公司")],
        ["纳税人资格", str(enterprise.get("taxpayer_type") or "一般纳税人")],
        ["报告期间", period],
    ]


def _small_business_rows(enterprise: dict, balance: dict, income: dict) -> list[list[str]]:
    assets = _to_float(balance.get("total_assets"))
    profit = _to_float(income.get("operating_profit"))
    return [
        ["序号", "判定条件", "标准要求", "企业实际情况", "是否符合"],
        ["1", "行业范围", "非限制和禁止行业", str(enterprise.get("industry") or "未填写"), "需确认"],
        ["2", "从业人数", "<=300人", "报表未披露", "待确认"],
        ["3", "资产总额", "<=5,000万元", _format_wan(assets), "是" if assets <= 50_000_000 else "否"],
        ["4", "应纳税所得额", "<=300万元", _format_wan(profit), "是" if profit <= 3_000_000 else "否"],
    ]


def _scale_rows(balance: dict, income: dict) -> list[list[str]]:
    return [
        ["项目", "金额", "项目", "金额"],
        ["资产总计", _format_wan(balance.get("total_assets")), "负债合计", _format_wan(balance.get("total_liabilities"))],
        ["货币资金", _format_wan(balance.get("cash")), "应收账款", _format_wan(balance.get("accounts_receivable"))],
        ["存货", _format_wan(balance.get("inventory")), "应付账款", _format_wan(balance.get("accounts_payable"))],
        ["营业收入", _format_wan(income.get("revenue")), "营业利润", _format_wan(income.get("operating_profit"))],
    ]


def _risk_overview_rows(balance: dict, income: dict, tax_draft: dict) -> list[list[str]]:
    liability_ratio = _ratio(balance.get("total_liabilities"), balance.get("total_assets"))
    current_ratio = _ratio(balance.get("cash"), balance.get("total_liabilities"))
    profit_margin = _ratio(income.get("operating_profit"), income.get("revenue"))
    vat_burden = _ratio(tax_draft.get("vat_payable"), income.get("revenue"))
    return [
        ["风险类别", "风险指标", "实际值", "安全值", "风险等级"],
        ["资本结构", "资产负债率", liability_ratio, "<70%", _risk_level(_numeric_ratio(balance.get("total_liabilities"), balance.get("total_assets")), high=0.7, medium=0.55, higher_is_risk=True)],
        ["短期偿债", "现金/负债", current_ratio, ">20%", _risk_level(_numeric_ratio(balance.get("cash"), balance.get("total_liabilities")), high=0.05, medium=0.2, higher_is_risk=False)],
        ["盈利能力", "营业利润率", profit_margin, ">5%", _risk_level(_numeric_ratio(income.get("operating_profit"), income.get("revenue")), high=0.03, medium=0.05, higher_is_risk=False)],
        ["运营效率", "应收账款占收入", _ratio(balance.get("accounts_receivable"), income.get("revenue")), "<20%", "需关注"],
        ["税务合规", "增值税税负率", vat_burden, "3%-5%", "需复核"],
        ["税收优惠", "小微企业资格", "需人工确认", "资产<5000万", "待确认"],
    ]


def _solvency_rows(balance: dict) -> list[list[str]]:
    return [
        ["指标名称", "计算公式", "实际值", "行业安全值", "评估结果"],
        ["资产负债率", "负债/资产", _ratio(balance.get("total_liabilities"), balance.get("total_assets")), "<70%", _risk_level(_numeric_ratio(balance.get("total_liabilities"), balance.get("total_assets")), high=0.7, medium=0.55, higher_is_risk=True)],
        ["现金比率", "货币资金/流动负债", _ratio(balance.get("cash"), balance.get("total_liabilities")), ">20%", "需关注"],
        ["应付账款占负债", "应付账款/负债", _ratio(balance.get("accounts_payable"), balance.get("total_liabilities")), "<50%", "需关注"],
        ["权益乘数", "资产/所有者权益", _equity_multiplier(balance), "<3.0", "需结合所有者权益复核"],
    ]


def _profit_rows(income: dict) -> list[list[str]]:
    gross_profit = _to_float(income.get("revenue")) - _to_float(income.get("cost"))
    return [
        ["指标", "金额（万元）", "比率", "行业参考", "评估"],
        ["营业收入", _format_wan(income.get("revenue")), "-", "-", "收入规模需持续观察"],
        ["毛利", _format_wan(gross_profit), _ratio(gross_profit, income.get("revenue")), "25-35%", "关注成本率"],
        ["营业利润", _format_wan(income.get("operating_profit")), _ratio(income.get("operating_profit"), income.get("revenue")), ">8%", "需改善"],
        ["净利润", _format_wan(income.get("net_profit") or income.get("operating_profit")), _ratio(income.get("net_profit") or income.get("operating_profit"), income.get("revenue")), ">5%", "需改善"],
        ["期间费用", _format_wan(income.get("expense")), _ratio(income.get("expense"), income.get("revenue")), "<15%", "需复核"],
    ]


def _working_capital_rows(balance: dict, income: dict) -> list[list[str]]:
    return [
        ["项目", "金额/指标", "诊断提示"],
        ["应收账款", _format_wan(balance.get("accounts_receivable")), "结合账龄和客户集中度判断回收风险"],
        ["存货", _format_wan(balance.get("inventory")), "关注呆滞料和项目型库存占用"],
        ["现金净变动", _format_wan(balance.get("cash_net_movement")), "为负时需压降非必要支出并强化回款"],
        ["营业收入", _format_wan(income.get("revenue")), "作为现金回款计划基准"],
    ]


def _tax_rows(tax_draft: dict) -> list[list[str]]:
    return [
        ["税种/项目", "累计金额（万元）", "说明"],
        ["销项销售额", _format_wan(tax_draft.get("output_amount")), "本期销项不含税销售额"],
        ["销项税额", _format_wan(tax_draft.get("output_tax")), "本期销项税额"],
        ["进项金额", _format_wan(tax_draft.get("input_amount")), "本期进项不含税金额"],
        ["进项税额", _format_wan(tax_draft.get("input_tax")), "本期可抵扣进项税额"],
        ["增值税", _format_wan(tax_draft.get("vat_payable")), "销项税额减进项税额"],
        ["附加税费", _format_wan(tax_draft.get("surcharge_estimate")), "按申报草稿估算"],
    ]


def _risk_cost_rows(balance: dict, income: dict, tax_draft: dict) -> list[list[str]]:
    estimated_payable = _to_float(balance.get("accounts_payable"))
    ar = _to_float(balance.get("accounts_receivable"))
    profit = max(_to_float(income.get("operating_profit")), 0)
    return [
        ["风险事项", "潜在损失（万元）", "计算依据"],
        ["暂估应付-企业所得税", _format_wan(estimated_payable * 0.25), "暂估额 x 25%"],
        ["暂估应付-增值税损失", _format_wan(estimated_payable / 1.13 * 0.13), "暂估额/1.13 x 13%"],
        ["应收账款坏账风险", _format_wan(ar * 0.05), "应收账款余额 x 5%"],
        ["无法享受小微优惠（年）", _format_wan(profit * 0.2), "利润 x (25%-5%)"],
        ["申报数据复核风险", _format_wan(tax_draft.get("vat_payable")), "以本期应纳增值税为复核基准"],
    ]


def _appendix_rows() -> list[list[str]]:
    return [
        ["指标", "安全线", "警戒线", "高危线"],
        ["资产负债率", "<60%", "70%", ">85%"],
        ["流动比率", ">1.5", "1.0", "<1.0"],
        ["速动比率", ">1.0", "0.8", "<0.8"],
        ["净利率", ">5%", "3%", "<3%"],
        ["毛利率", "25-35%", "<20%", "<15%"],
        ["应收账款周转天数", "<60天", "90天", ">120天"],
        ["应付账款暂估占比", "<10%", "30%", ">50%"],
        ["增值税税负率", "3%-5%", "<2% 或 >6%", "异常波动"],
    ]


def _core_findings(balance: dict, income: dict, tax_draft: dict) -> list[str]:
    return [
        f"资产负债率为 {_ratio(balance.get('total_liabilities'), balance.get('total_assets'))}，需关注资本结构安全边界。",
        f"本期营业收入为 {_format_wan(income.get('revenue'))}，营业利润率为 {_ratio(income.get('operating_profit'), income.get('revenue'))}。",
        f"本期应纳增值税为 {_format_wan(tax_draft.get('vat_payable'))}，申报前需核对未匹配发票和异常流水。",
    ]


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


def _taxpayer_label(value) -> str:
    normalized = str(value or "").strip().upper()
    if normalized == "GENERAL":
        return "一般纳税人"
    if normalized == "SMALL":
        return "小规模纳税人"
    return str(value or "一般纳税人")


def _equity_multiplier(balance: dict) -> str:
    assets = _to_float(balance.get("total_assets"))
    liabilities = _to_float(balance.get("total_liabilities"))
    equity = _to_float(balance.get("owner_equity")) or assets - liabilities
    if equity == 0:
        return "数据不足"
    return f"{assets / equity:.2f}"


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


def _format_wan(value) -> str:
    return f"{_to_float(value) / 10000:.2f} 万元"


def _to_float(value) -> float:
    try:
        return float(Decimal(str(value or "0").replace(",", "")))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0
