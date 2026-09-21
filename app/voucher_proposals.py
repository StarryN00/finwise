"""按学到的习惯，为一笔银行流水提出凭证。

提案不是凭证。它必须说明依据（学自哪几张历史凭证）、置信度，以及哪些地方
是凑不出来的。凑不出来时宁可不提案，让人在卡片上定 —— 做账的每一笔都要
有人负责，系统的价值在于把"人要判断的"从几十条压到几条。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from app.voucher_history import (
    INPUT_TAX, VoucherTemplate, normalize_party,
)

PROPOSER_VERSION = "voucher-proposal-v1"
CENT = Decimal("0.01")
BANK_ACCOUNT_NAME = "银行存款"


class ProposedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_code: StrictStr
    account_name: StrictStr
    debit: Decimal = Decimal("0.00")
    credit: Decimal = Decimal("0.00")


class VoucherProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["PROPOSAL", "ABSTAIN"]
    summary: StrictStr = ""
    lines: list[ProposedLine] = Field(default_factory=list)
    confidence: StrictInt = 0
    basis: list[StrictStr] = Field(default_factory=list)
    reason: StrictStr = ""
    template_key: StrictStr = ""

    def balanced(self) -> bool:
        return (sum((l.debit for l in self.lines), Decimal("0.00"))
                == sum((l.credit for l in self.lines), Decimal("0.00")))


def _confidence(template: VoucherTemplate, tax_known: bool, settle_only: bool = False) -> int:
    """置信度反映证据量，不是感觉。

    结算过的次数是最强的依据；只挂过账没结算过时结构是推断的，要压低。
    需要拆进项税却没找到对应发票时，金额是凑的，必须压到最低。
    """
    if settle_only:
        # 纯结算的分录很简单，但"这笔付款确实没有票"是个假设，需要人确认。
        return 60
    base = 55 if template.settlements == 0 else min(95, 60 + template.settlements * 5)
    if len(template.expense_accounts) > 1:
        base -= 10  # 历史上这个对象用过多个费用科目，选哪个并不确定
    return max(30, base)


def propose(
    *,
    bank_account_code: str,
    bank_account_name: str,
    counterparty: str,
    summary: str,
    amount: Decimal,
    direction: Literal["PAYMENT", "RECEIPT"],
    templates: dict[tuple[str, str], VoucherTemplate],
    input_tax: Optional[Decimal] = None,
    expense_account: Optional[tuple[str, str]] = None,
    expense_basis: str = "",
) -> VoucherProposal:
    key = (normalize_party(counterparty), direction)
    template = templates.get(key)
    if template is None:
        return VoucherProposal(
            outcome="ABSTAIN",
            reason=(f"没有“{counterparty or '未知对方'}”的历史做法可循"
                    if counterparty else "这笔流水没有对方户名，无法按往来对象取用历史做法"))
    # 收款不需要费用科目：投资款就是借银行 / 贷实收资本。这道守卫只管付款。
    if direction == "PAYMENT" and not template.expense_accounts and template.via_party:
        return VoucherProposal(outcome="ABSTAIN", template_key=f"{key[0]}|{key[1]}",
                               reason=f"历史上“{template.party}”只有往来过渡，没有固定的费用或资产科目")

    # 付款与收票是两件事。历史上跟这个供应商有过"收票并付款"的凭证，不代表
    # 这一笔付款也带票 —— 真实账里 记-007、记-010、记-012 都是纯付款冲应付，
    # 借应付账款 / 贷银行，压根不拆进项税。没找到发票时按纯结算处理，
    # 而不是拒绝提案。
    tax = input_tax if input_tax is not None else Decimal("0.00")
    settle_only = template.splits_input_tax and input_tax is None

    lines: list[ProposedLine] = []
    party_line = ProposedLine(account_code=template.party_account,
                              account_name=template.party_account_name)
    if direction == "PAYMENT":
        if settle_only:
            # 纯结算：冲减往来，不确认费用也不拆税。
            lines.append(party_line.model_copy(update={"debit": amount}))
            lines.append(ProposedLine(account_code=bank_account_code,
                                      account_name=bank_account_name, credit=amount))
        elif expense_account or template.expense_accounts:
            # 费用科目优先用按摘要判断出来的。往来模板里最常用的那个只是兜底 ——
            # 同一个人可以报销办公费、差旅费、餐费、福利费，挂谁的账由往来对象
            # 决定，记什么费用由摘要决定，这两件事不能混。
            code, name = expense_account or template.expense_accounts[0]
            lines.append(ProposedLine(account_code=code, account_name=name, debit=amount - tax))
            if tax > 0:
                lines.append(ProposedLine(account_code=INPUT_TAX, account_name="进项税额", debit=tax))
            lines.append(party_line.model_copy(update={"credit": amount}))
        if not settle_only:
            lines.append(party_line.model_copy(update={"debit": amount}))
            lines.append(ProposedLine(account_code=bank_account_code,
                                      account_name=bank_account_name, credit=amount))
    else:
        lines.append(ProposedLine(account_code=bank_account_code,
                                  account_name=bank_account_name, debit=amount))
        lines.append(party_line.model_copy(update={"credit": amount}))

    proposal = VoucherProposal(
        outcome="PROPOSAL", summary=summary or template.party,
        lines=lines, confidence=_confidence(template, input_tax is not None, settle_only),
        template_key=f"{key[0]}|{key[1]}",
        basis=([f"未找到对应进项发票，按纯结算处理：冲减 {template.party_account_name}，不确认费用"]
               if settle_only else []) +
              ([expense_basis] if expense_basis and not settle_only else []) +
              [f"学自 {template.seen} 张历史凭证（{'、'.join(template.examples)}）",
               f"其中结算过 {template.settlements} 次",
               f"{'经' if template.via_party else '不经'}往来科目 {template.party_account} 过渡",
               f"{'拆' if template.splits_input_tax else '不拆'}进项税额"])
    if not proposal.balanced():
        return VoucherProposal(outcome="ABSTAIN", template_key=proposal.template_key,
                               reason="按历史做法组出的分录借贷不平，不予提案")
    return proposal
