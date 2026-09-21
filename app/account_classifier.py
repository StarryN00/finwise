"""按摘要判断记哪个科目。这一步是真正的语义判断，只能由模型做。

试过确定性的办法：学历史说法的精确匹配能覆盖一部分，字面重合则是负面结果
（14 个真实摘要对 0 错 4，"7月手机宽带费"因"7月"撞上"计提7月折旧"被判成
固定资产折旧）。会计科目之间的关系是语义的，不是字面的。

因此这里交给模型，但加三道约束：
  * 只能在这家企业**自己在用**的科目里选，不能发明科目；
  * 必须引用历史上用过该科目的凭证号作为依据；
  * 选不出来要明说弃权，不许硬挑一个。
选中之后由人确认一次，沉淀成规则，下个月同样的说法不再问模型。
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from app.voucher_history import AccountRule, normalize_party

CLASSIFIER_VERSION = "account-classifier-v1"
MAX_CANDIDATES = 40
# 低于这个置信度不自动采用。实测在留出月份上对 8 错 5 弃权 1（14 个真实摘要），
# 这个准确率不足以无人值守，但每错一次人工改一次就沉淀成规则，下月不再问。
AUTO_ADOPT_CONFIDENCE = 85

INSTRUCTION = (
    "你要判断一笔银行流水应当记入哪个会计科目。"
    "只能从给出的候选科目里选一个，绝不能发明科目编码或名称。"
    "候选里没有合适的就选择弃权。不要因为某个科目最常用就选它。"
    "判断依据是摘要与对方户名的业务含义，不是字面重合："
    "例如“购买水果礼盒”是职工福利，不是办公用品。"
    "判断顺序：先由摘要的业务性质定下该记哪一类费用，再看 party_history。"
    "party_history 是这个往来对象过去用过的科目，只用于在语义上同样合适的"
    "多个科目之间取舍 —— 例如企业同时有管理费用_差旅费与销售费用_差旅费，"
    "选哪个取决于这个人属哪个部门，那写在他过去的凭证里。"
    "绝不能用 party_history 覆盖摘要的业务性质："
    "一个人常报销办公费，不代表他这次买的水果礼盒也是办公费。"
)

SCHEMA_HINT = (
    "只返回一个 JSON 对象，不要解释文字。结构为："
    '{"outcome":"PICK"或"ABSTAIN","account_code":"","account_name":"",'
    '"reason":"不超过40字的中文理由","evidence":["历史凭证号"],"confidence":0到100}。'
    "outcome 为 ABSTAIN 时 account_code 与 account_name 留空字符串。"
    "account_code 必须原样取自候选列表，不得改写。"
)


class AccountChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["PICK", "ABSTAIN"]
    account_code: StrictStr = ""
    account_name: StrictStr = ""
    reason: StrictStr = ""
    evidence: list[StrictStr] = Field(default_factory=list)
    confidence: StrictInt = 0


class AccountReader(Protocol):
    def classify(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


def candidates(vocabulary: list[AccountRule], limit: int = MAX_CANDIDATES) -> list[dict[str, Any]]:
    """交给模型的候选科目：这家企业自己在用的，按使用频次排序。"""
    return [{"account_code": rule.account_code, "account_name": rule.account_name,
             "used": rule.seen, "examples": rule.examples[:2]}
            for rule in vocabulary[:limit]]


def party_history(party: str, vouchers, limit: int = 5) -> list[dict[str, Any]]:
    """这个往来对象历史上记过哪些科目。

    企业常有并列的同名科目（560205 管理费用_差旅费 与 560106 销售费用_差旅费），
    选哪个取决于这个人属哪个部门 —— 那不是摘要能看出来的，但写在他过去的凭证里。
    """
    from collections import Counter
    from app.voucher_history import _expense_lines

    key = normalize_party(party)
    if not key:
        return []
    tally: Counter = Counter()
    for voucher in vouchers:
        if not any(normalize_party(line.account_name) == key for line in voucher.lines):
            continue
        for line in _expense_lines(voucher):
            tally[(line.account_code, line.account_name)] += 1
    return [{"account_code": code, "account_name": name, "used": count}
            for (code, name), count in tally.most_common(limit)]


def classify(
    *, summary: str, counterparty: str, amount: str, direction: str,
    vocabulary: list[AccountRule], reader: AccountReader,
    party_accounts: Optional[list[dict[str, Any]]] = None,
) -> AccountChoice:
    """选科目。模型只在闭集里选，选完还要核对它确实选了集合里的东西。"""
    allowed = {rule.account_code: rule.account_name for rule in vocabulary}
    if not allowed:
        return AccountChoice(outcome="ABSTAIN", reason="这家企业还没有可参考的在用科目")
    payload = {
        "summary": summary, "counterparty": counterparty,
        "amount": amount, "direction": direction,
        "party_history": party_accounts or [],
        "candidates": candidates(vocabulary),
    }
    try:
        raw = reader.classify(payload)
        choice = AccountChoice.model_validate(raw)
    except Exception as exc:
        return AccountChoice(outcome="ABSTAIN", reason=f"科目判断未完成：{exc}"[:80])
    if choice.outcome != "PICK":
        return choice
    if not choice.account_code:
        return AccountChoice(outcome="ABSTAIN", confidence=0,
                             reason="返回声称选定了科目，却没有给出科目编码")
    # 模型可能返回一个看似合理却不在候选里的科目编码。闭集必须在这里再核一次，
    # 否则"不发明科目"只是提示词里的一句话，不是保证。
    if choice.account_code not in allowed:
        return AccountChoice(outcome="ABSTAIN", confidence=0,
                             reason=f"返回的科目 {choice.account_code} 不在该企业在用科目内，不予采用")
    return choice.model_copy(update={"account_name": allowed[choice.account_code]})


def auto_adoptable(choice: AccountChoice) -> bool:
    """能不能不经人看就用。默认不能 —— 科目归类错了不会报错，只会成为错账。"""
    return choice.outcome == "PICK" and choice.confidence >= AUTO_ADOPT_CONFIDENCE


class GatewayAccountReader:
    """经 Agent Gateway 调用。分类是高频轻任务，走快档模型。"""

    def __init__(self, provider, settings):
        self.provider = provider
        self.settings = settings
        self.calls: list[dict[str, Any]] = []

    def classify(self, payload: dict[str, Any]) -> dict[str, Any]:
        # 快档模型默认开思考模式，推理会吃掉输出预算。候选科目多达 40 个时，
        # 1200 的默认额度连一个短 JSON 都留不下，表现为"返回的不是合法 JSON"。
        output, metadata = self.provider.complete_json(
            model=self.settings.model_for("MATERIAL_GUIDANCE"),
            system=SCHEMA_HINT,
            user=INSTRUCTION + "\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True),
            max_tokens=4000,
        )
        self.calls.append(metadata)
        return output
