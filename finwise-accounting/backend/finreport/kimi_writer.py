from __future__ import annotations

import json
import os

from openai import OpenAI

from .fallback_texts import FALLBACK_TEXTS


SYSTEM_PROMPT = """你是一位资深注册会计师与企业财务顾问,正在撰写一份《企业财务健康诊断报告》的某一段文字。

请严格遵守以下规则:
1. 只能使用用户消息中【已核算指标】里给出的数字,严禁编造、估算或修改任何数字。
2. 输出**纯文本中文**,不要使用 markdown 标题(# / ##),但可以用 **加粗** 标注关键词。
3. 行文风格:专业、克制、先结论后论据,不使用"我们认为""我们建议"等第一人称。
4. 数字与中文之间不加空格;百分号紧贴数字;万元、天等单位紧贴数字。
5. 不要输出任何前言、致辞、致谢、"以下是..."这类铺垫语句,直接进入正文。
6. 不要超过用户指定的字数范围(允许误差 ±15%)。
7. 不要重复用户消息中的字段名(如不要写"已核算指标显示..."),直接用数字论述。
"""


SECTION_CONFIGS = {
    "W1": {
        "name": "执行摘要-五项重大风险",
        "format_hint": "输出 5 个有序条目(用 1. 2. 3. 4. 5. 编号),每条格式为:\n「**风险标题**:数据描述」,风险标题加粗。\n5 个风险依次为:账务处理严重异常 / 现金流极度枯竭 / 持续经营亏损 / 盈利能力恶化 / 高额利息侵蚀利润。",
        "word_count": "每条 30-50 字",
        "metrics_keys": ["应付账款负数", "其他应付款负数", "货币资金", "短期借款", "现金比率", "近两年净利润", "累计未分配利润", "净利率", "毛利率_2024", "毛利率_2025", "管理费用率", "年利息支出"],
    },
    "W2": {"name": "小微企业优惠判定结论", "format_hint": "一段连续文字,先客观陈述当期是否产生节税效益,再做未来盈利情景测算,最后判断形式合规性。", "word_count": "100-150 字", "metrics_keys": ["应纳税所得额", "资产总额", "标准税率_25", "小微税率_5"]},
    "W3": {"name": "偿债能力风险总结-核心矛盾", "format_hint": "一段连续文字,前半段引用 资产负债率/流动比率/速动比率 说明账面达标,后半段用 现金比率/货币资金/短期借款 揭示矛盾,最后给出风险结论。", "word_count": "100-150 字", "metrics_keys": ["资产负债率", "流动比率", "速动比率", "现金比率", "货币资金", "短期借款"]},
    "W4": {"name": "短期偿债改善建议", "format_hint": "输出 4 条有序行动建议(用 1. 2. 3. 4. 编号),每条是一句具体可执行的动作,涵盖:银行续贷、清理预付账款、压缩存货、核实其他应付款。", "word_count": "每条 20-35 字", "metrics_keys": ["短期借款", "应付账款负数", "其他应付款负数", "存货周转天数"]},
    "W5": {"name": "研发费用加计扣除提示", "format_hint": "一段连续文字,顺序为:政策介绍(制造业 100% 加计扣除)→ 当期可加计金额测算 → 因亏损当期无效但可递延 → 操作建议(规范归集、设辅助账)。", "word_count": "80-120 字", "metrics_keys": ["研究费用", "加计金额", "当期是否盈利"]},
    "W6": {"name": "应收账款管理改善", "format_hint": "一段连续文字,引用 应收账款余额变动 + 周转天数变动,评价回款管理改善,并指出这是资金紧张背景下的合理策略。", "word_count": "60-100 字", "metrics_keys": ["应收账款_2024", "应收账款_2025", "应收账款周转天数_2024", "应收账款周转天数_2025"]},
    "W7": {"name": "存货积压风险", "format_hint": "先一段连续文字描述风险(存货金额、周转天数、与正常水平对比),然后输出 3 条有序子弹建议(用 - 开头):\n- 库龄分析\n- 以销定产\n- 呆滞存货处理", "word_count": "首段 80-110 字,3 条子弹各 20-30 字", "metrics_keys": ["存货", "存货周转天数", "库存商品", "原材料"]},
    "W8": {"name": "流动性危机预警", "format_hint": "强警示语气的连续段落,引用 货币资金 vs 短期借款 vs 年利息,然后用「企业的持续经营高度依赖:」引出 3 条有序条目(1. 2. 3.),最后用「**结论:**」开头给出一句决定性判断。", "word_count": "120-180 字", "metrics_keys": ["货币资金", "短期借款", "年利息支出", "资产负债率", "存货周转天数", "实收资本变动"]},
    "W9": {"name": "总结与展望", "format_hint": "分 4 段输出,每段开头用「**诊断结论:**」「**积极因素:**」「**综合策略:**」「**目标:**」加粗标识:\n- 诊断结论段:列出 3 大致命弱点(现金流枯竭/账务不规范/持续经营存疑)\n- 积极因素段:列举回款改善、增值税合规、小微资格、股东追加投资\n- 综合策略段:短期(1-3月)/中期(3-12月)/长期(1-3年)三阶段策略\n- 目标段:6/12/24 个月可量化目标", "word_count": "总计 400-600 字", "metrics_keys": ["资产负债率", "流动比率", "货币资金", "短期借款", "近两年净利润", "应收账款周转改善", "增值税税负率", "资产总额", "实收资本变动"]},
}


def generate_all_sections(context: dict) -> dict[str, str]:
    return {section_id: call_kimi(section_id, context) for section_id in SECTION_CONFIGS}


def call_kimi(section_id: str, context: dict, retry: int = 2) -> str:
    if not os.environ.get("MOONSHOT_API_KEY"):
        return FALLBACK_TEXTS[section_id]
    user_msg = build_user_prompt(section_id, context)
    models = ["kimi-k2-0905-preview", "moonshot-v1-32k"]
    for model in models:
        for attempt in range(retry + 1):
            try:
                client = OpenAI(api_key=os.environ.get("MOONSHOT_API_KEY"), base_url="https://api.moonshot.cn/v1")
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_msg}],
                    temperature=0.3,
                    max_tokens=800,
                )
                text = (resp.choices[0].message.content or "").strip()
                if validate_output(section_id, text):
                    return text
            except Exception:
                if attempt == retry and model == models[-1]:
                    return FALLBACK_TEXTS[section_id]
    return FALLBACK_TEXTS[section_id]


def build_user_prompt(section_id: str, context: dict) -> str:
    cfg = SECTION_CONFIGS[section_id]
    metrics_json = json.dumps({k: context[k] for k in cfg["metrics_keys"] if k in context}, ensure_ascii=False, indent=2)
    return f"""请撰写报告中【{cfg["name"]}】部分的正文。

【已核算指标】
{metrics_json}

【格式要求】
{cfg["format_hint"]}

【字数】
{cfg["word_count"]}

请现在直接输出正文。"""


def validate_output(section_id: str, text: str) -> bool:
    if not text or any(bad in text for bad in ["以下是", "作为 AI", "我无法", "无法提供"]):
        return False
    if section_id in {"W1", "W4", "W8"} and not ("1." in text and "2." in text):
        return False
    if section_id == "W7" and "-" not in text:
        return False
    if section_id == "W9" and "诊断结论" not in text:
        return False
    return len(text.strip()) >= 20
