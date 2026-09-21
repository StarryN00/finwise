"""从账套已有的凭证里学习做账习惯。

规则不该由系统发明。同一家代账公司对同一个往来对象的处理方式是固定的：
侯文军的报销永远挂 224101、山东高精橡塑的采购永远走 1403 原材料 + 220217。
这些习惯就写在他们自己过去几个月的凭证里，读出来即可。

摘要不能当键 —— 实测同一家企业 8 月出现 29 种摘要，其中 18 种是当月新写法。
会计每月随手写摘要，习惯固化在往来对象和科目结构上，不在文字里。
"""
from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

HISTORY_VERSION = "voucher-history-v1"
BANK_PREFIX = "1002"
INPUT_TAX = "22210101"
OUTPUT_TAX = "22210107"
# 往来过渡科目：应付账款、其他应付款、应收账款、其他应收款、实收资本
PARTY_PREFIXES = ("2202", "2203", "2241", "1122", "1123", "1221", "3001")
CENT = Decimal("0.01")


class JournalError(ValueError):
    pass


def _money(value: Any) -> Decimal:
    text = str(value if value is not None else "").strip().replace(",", "")
    if text in {"", "-", "nan", "None"}:
        return Decimal("0.00")
    try:
        return Decimal(text).quantize(CENT)
    except (InvalidOperation, ValueError) as exc:
        raise JournalError(f"金额无法识别：{value!r}") from exc


class VoucherLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_code: StrictStr
    account_name: StrictStr
    summary: StrictStr = ""
    debit: Decimal = Decimal("0.00")
    credit: Decimal = Decimal("0.00")

    @property
    def is_bank(self) -> bool:
        return self.account_code.startswith(BANK_PREFIX)

    @property
    def is_input_tax(self) -> bool:
        return self.account_code == INPUT_TAX

    @property
    def is_party(self) -> bool:
        return self.account_code.startswith(PARTY_PREFIXES)


class Voucher(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: StrictStr
    period: StrictStr
    date: StrictStr
    summary: StrictStr = ""
    lines: list[VoucherLine]

    @property
    def bank_lines(self) -> list[VoucherLine]:
        return [line for line in self.lines if line.is_bank]

    @property
    def bank_driven(self) -> bool:
        return bool(self.bank_lines)

    @property
    def direction(self) -> Optional[str]:
        """银行贷方是付款，借方是收款。没有银行行就不是流水驱动的凭证。"""
        bank = self.bank_lines
        if not bank:
            return None
        if all(line.credit > 0 for line in bank):
            return "PAYMENT"
        if all(line.debit > 0 for line in bank):
            return "RECEIPT"
        return None

    @property
    def bank_total(self) -> Decimal:
        return sum((line.credit + line.debit for line in self.bank_lines), Decimal("0.00"))

    def balanced(self) -> bool:
        return (sum((l.debit for l in self.lines), Decimal("0.00"))
                == sum((l.credit for l in self.lines), Decimal("0.00")))


COLUMNS = ("科目编码", "科目", "日期", "凭证号", "摘要", "借方", "贷方")


def parse_journal(sheet: dict[str, Any]) -> list[Voucher]:
    """读账套导出的序时账。一张凭证的各行由凭证号加期间分组。"""
    rows = [r for r in sheet["rows"] if any(str(v or "").strip() for v in r["values"])]
    header = next((index for index, row in enumerate(rows[:20])
                   if all(any(name == re.sub(r"\s+", "", str(v or "")) for v in row["values"])
                          for name in COLUMNS)), None)
    if header is None:
        raise JournalError("未能在序时账里定位表头行")
    labels = {re.sub(r"\s+", "", str(v or "")): index
              for index, v in enumerate(rows[header]["values"])}
    grouped: dict[tuple[str, str], list[VoucherLine]] = {}
    meta: dict[tuple[str, str], tuple[str, str]] = {}
    for row in rows[header + 1:]:
        values = row["values"]

        def cell(name: str) -> Any:
            index = labels[name]
            return values[index] if index < len(values) else None

        day = str(cell("日期") or "").strip()
        number = str(cell("凭证号") or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or not number:
            continue
        key = (day[:7], number)
        grouped.setdefault(key, []).append(VoucherLine(
            account_code=re.sub(r"\s+", "", str(cell("科目编码") or "")),
            account_name=str(cell("科目") or "").strip(),
            summary=str(cell("摘要") or "").strip(),
            debit=_money(cell("借方")), credit=_money(cell("贷方"))))
        meta.setdefault(key, (day, str(cell("摘要") or "").strip()))
    return [Voucher(number=number, period=period, date=meta[(period, number)][0],
                    summary=meta[(period, number)][1], lines=lines)
            for (period, number), lines in grouped.items()]


def normalize_party(name: str) -> str:
    return re.sub(r"[\s（）()·、]", "", str(name or ""))


class VoucherTemplate(BaseModel):
    """一个往来对象在某个方向上的固定做法。"""

    model_config = ConfigDict(extra="forbid")

    party: StrictStr
    direction: Literal["PAYMENT", "RECEIPT"]
    party_account: StrictStr
    party_account_name: StrictStr
    expense_accounts: list[tuple[StrictStr, StrictStr]] = Field(default_factory=list)
    splits_input_tax: StrictBool = False
    via_party: StrictBool = True
    seen: StrictInt = 1
    # 其中有多少张是真正结算过的（带银行行）。只挂过账没付过款的对象，
    # 科目习惯可信但结算结构未知，提案时要降低置信度。
    settlements: StrictInt = 0
    examples: list[StrictStr] = Field(default_factory=list)


def _counterpart(voucher: Voucher) -> Optional[VoucherLine]:
    """凭证里的往来对象。优先取与银行金额相等的那一行。"""
    parties = [line for line in voucher.lines if line.is_party]
    if not parties:
        return None
    total = voucher.bank_total
    exact = [line for line in parties if line.debit == total or line.credit == total]
    return (exact or parties)[0]


def _implied_direction(voucher: Voucher) -> Optional[str]:
    """凭证的方向。

    有银行行时看银行的借贷。没有银行行的挂账凭证同样有价值 —— "这个供应商
    走 1403 原材料 + 220217" 这条习惯就写在挂账凭证里，将来付款时要用。
    这时按往来科目的方向推断：贷方是欠对方、将来付款；借方反之。
    """
    direction = voucher.direction
    if direction:
        return direction
    party = _counterpart(voucher)
    if party is None:
        return None
    if party.credit > 0:
        return "PAYMENT"
    if party.debit > 0:
        return "RECEIPT"
    return None


def learn_templates(vouchers: Iterable[Voucher]) -> dict[tuple[str, str], VoucherTemplate]:
    """从借贷平衡的凭证里学做账习惯。月末结转类没有往来对象，自然不在此列。

    科目习惯从所有凭证学，凭证结构（是否经往来过渡）只从流水驱动的那些学：
    挂账凭证只有一侧，拿它投票会把"经往来过渡"这个特征算错。
    """
    drafts: dict[tuple[str, str], list[Voucher]] = {}
    for voucher in vouchers:
        direction = _implied_direction(voucher)
        if not direction or not voucher.balanced():
            continue
        party = _counterpart(voucher)
        if party is None:
            continue
        drafts.setdefault((normalize_party(party.account_name), direction), []).append(voucher)

    templates: dict[tuple[str, str], VoucherTemplate] = {}
    for key, group in drafts.items():
        party = _counterpart(group[-1])
        expenses: Counter = Counter()
        tax_votes = 0
        via_votes = 0
        for voucher in group:
            counterpart = _counterpart(voucher)
            for line in voucher.lines:
                if line.is_bank or line.is_party or line.is_input_tax:
                    continue
                if line.debit > 0:
                    expenses[(line.account_code, line.account_name)] += 1
            tax_votes += any(line.is_input_tax for line in voucher.lines)
        # 只有流水驱动的凭证能说明"是否经往来科目过渡"：挂账凭证只有一侧。
        structural = [v for v in group if v.bank_driven]
        for voucher in structural:
            party_lines = [l for l in voucher.lines
                           if normalize_party(l.account_name) == key[0] and l.is_party]
            via_votes += any(l.debit > 0 for l in party_lines) and any(l.credit > 0 for l in party_lines)
        templates[key] = VoucherTemplate(
            party=party.account_name, direction=key[1],
            party_account=party.account_code, party_account_name=party.account_name,
            expense_accounts=[code for code, _ in expenses.most_common(3)],
            splits_input_tax=tax_votes * 2 > len(group),
            via_party=bool(structural) and via_votes * 2 > len(structural),
            seen=len(group), settlements=len(structural),
            examples=[v.number for v in group[:3]])
    return templates


class AccountRule(BaseModel):
    """一条"某种说法对应某个科目"的规则，学自账套已有的凭证。"""

    model_config = ConfigDict(extra="forbid")

    pattern: StrictStr
    account_code: StrictStr
    account_name: StrictStr
    seen: StrictInt = 1
    examples: list[StrictStr] = Field(default_factory=list)


def _expense_lines(voucher: Voucher) -> list[VoucherLine]:
    """凭证里真正表示"记什么"的行：借方、非银行、非往来、非税。"""
    return [line for line in voucher.lines
            if line.debit > 0 and not (line.is_bank or line.is_party or line.is_input_tax)]


def learn_expense_rules(vouchers: Iterable[Voucher]) -> list[AccountRule]:
    """学"摘要说法 → 费用或资产科目"。

    往来对象决定挂谁的账，摘要决定记什么费用 —— 同一个人可以报销办公费、
    差旅费、餐费、福利费，只有摘要能区分。这两件事必须分开学。
    """
    tally: dict[tuple[str, str, str], list[str]] = {}
    for voucher in vouchers:
        text = normalize_party(voucher.summary)
        if not text:
            continue
        for line in _expense_lines(voucher):
            tally.setdefault((text, line.account_code, line.account_name), []).append(voucher.number)
    rules = [AccountRule(pattern=pattern, account_code=code, account_name=name,
                         seen=len(numbers), examples=numbers[:3])
             for (pattern, code, name), numbers in tally.items()]
    return sorted(rules, key=lambda rule: -rule.seen)


def account_vocabulary(vouchers: Iterable[Voucher]) -> list[AccountRule]:
    """这家企业实际在用的费用与资产科目，按使用频次排序。

    科目名本身就是最好的匹配线索：流水摘要"加油打车费"里有"加油"，
    企业的科目表里正好有"加油费"。不必外部科目表，用他们自己的。
    """
    tally: dict[tuple[str, str], list[str]] = {}
    for voucher in vouchers:
        for line in _expense_lines(voucher):
            tally.setdefault((line.account_code, line.account_name), []).append(voucher.number)
    return sorted([AccountRule(pattern=normalize_party(name), account_code=code,
                               account_name=name, seen=len(numbers), examples=numbers[:3])
                   for (code, name), numbers in tally.items()],
                  key=lambda rule: -rule.seen)


def match_account(summary: str, rules: list[AccountRule], vocabulary: list[AccountRule]
                  ) -> tuple[Optional[AccountRule], str]:
    """按摘要找科目，只认学过的原话。

    试过按字面重合去对历史说法和科目名，实测是负面结果：14 个真实摘要里
    对 0 个、错 4 个。"出差车费"因为"车费"被判成汽车费（实为差旅费），
    "7月手机宽带费"因为"7月"撞上"计提7月折旧"被判成固定资产折旧。
    字面重合在会计科目上没有语义效力，产出的是自信的错误 —— 比不给答案更糟。

    对不上就返回 None：交给模型在企业自己的科目表里选，或者出卡让人定。
    """
    text = normalize_party(summary)
    if not text:
        return None, "流水没有摘要"
    exact = [rule for rule in rules if rule.pattern == text]
    if exact:
        best = max(exact, key=lambda rule: rule.seen)
        return best, f"历史上“{summary}”记过 {best.seen} 次 {best.account_name}"
    return None, f"“{summary}”不在历史说法里，需要按科目含义判断"

