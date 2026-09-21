"""把账套导出的余额表转成基线确认输入。

余额表的两个结构特征必须原样处理，不能压平：
  * 科目是多级的（2221 → 222101 → 22210101）。只有末级才是真正的余额，
    中间层是汇总；把它们一起加起来会重复计数。
  * 控制科目按净额列示，明细保持各自方向。往来科目下面既有应付的贷方余额，
    也有预付的借方余额，轧差之后才等于控制科目。

每一项余额都带回原件的行号，基线要求每个数字都能指回它的出处。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

PARSER_VERSION = "opening-balance-v1"
CENT = Decimal("0.01")

# 余额表表头是两行：第一行是期初/本期发生/期末，第二行是每段下的借方/贷方。
HEADER_TOP = ("科目编码", "科目", "期初余额", "期末余额")
# 需要辅助核算的往来类科目。判定只看它在余额表里有没有下级明细，
# 这里的前缀只用于在没有明细时提醒人补，不用于臆造明细。
AUXILIARY_PREFIXES = ("1122", "1123", "1221", "2202", "2203", "2241")


class OpeningBalanceError(ValueError):
    pass


class BalanceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: StrictInt
    account_code: StrictStr
    account_name: StrictStr
    closing_debit: Decimal
    closing_credit: Decimal
    children: list["BalanceLine"] = Field(default_factory=list)

    @property
    def net(self) -> Decimal:
        return self.closing_debit - self.closing_credit


def _money(value: Any) -> Decimal:
    text = str(value if value is not None else "").strip().replace(",", "")
    if text in {"", "-", "--", "nan", "None"}:
        return Decimal("0.00")
    try:
        return Decimal(text).quantize(CENT)
    except (InvalidOperation, ValueError) as exc:
        raise OpeningBalanceError(f"余额无法识别：{value!r}") from exc


def _locate_header(rows: list[dict[str, Any]]) -> int:
    for index, row in enumerate(rows[:20]):
        labels = {re.sub(r"\s+", "", str(v or "")) for v in row["values"]}
        if all(any(name in label for label in labels) for name in HEADER_TOP):
            return index
    raise OpeningBalanceError("未能在余额表里定位表头行")


def parse_balance_sheet(sheet: dict[str, Any]) -> list[BalanceLine]:
    """读出末级科目余额，并按科目编码的前缀关系还原层级。"""
    rows = [r for r in sheet["rows"] if any(str(v or "").strip() for v in r["values"])]
    header = _locate_header(rows)
    flat: list[BalanceLine] = []
    for row in rows[header + 2:]:
        values = row["values"]
        code = re.sub(r"\s+", "", str(values[1] if len(values) > 1 else ""))
        if not code or not code[0].isdigit():
            continue
        name = str(values[2] if len(values) > 2 else "").strip()
        flat.append(BalanceLine(row=row["row"], account_code=code, account_name=name,
                                closing_debit=_money(values[7] if len(values) > 7 else None),
                                closing_credit=_money(values[8] if len(values) > 8 else None)))
    if not flat:
        raise OpeningBalanceError("余额表里没有读到任何科目")

    codes = {line.account_code for line in flat}
    roots: list[BalanceLine] = []
    for line in flat:
        parents = [c for c in codes if len(c) < len(line.account_code)
                   and line.account_code.startswith(c)]
        if not parents:
            roots.append(line)
            continue
        nearest = max(parents, key=len)
        next(l for l in flat if l.account_code == nearest).children.append(line)
    return roots


def leaves(line: BalanceLine) -> list[BalanceLine]:
    """末级科目。中间层是汇总，连同末级一起加会重复计数。"""
    if not line.children:
        return [line]
    return [leaf for child in line.children for leaf in leaves(child)]


def trial_balance(roots: list[BalanceLine]) -> tuple[Decimal, Decimal]:
    return (sum((r.closing_debit for r in roots), Decimal("0.00")),
            sum((r.closing_credit for r in roots), Decimal("0.00")))


def to_confirmation(
    roots: list[BalanceLine], *, prior_period: str, close_reference: str,
    balance_source: dict[str, Any], close_source: dict[str, Any], sheet_name: str = "余额表",
) -> dict[str, Any]:
    """产出 BaselineConfirmation 的载荷。借贷不平时直接拒绝，不修饰。"""
    debit, credit = trial_balance(roots)
    if debit != credit:
        raise OpeningBalanceError(f"余额表期末试算不平衡：借 {debit}，贷 {credit}，差 {debit - credit}")

    balances = []
    for root in roots:
        detail = [leaf for leaf in leaves(root) if leaf.account_code != root.account_code]
        needs_auxiliary = bool(detail) and root.account_code.startswith(AUXILIARY_PREFIXES)
        auxiliary = []
        if needs_auxiliary:
            for leaf in detail:
                auxiliary.append({
                    "key": leaf.account_name or leaf.account_code,
                    "closing_debit": format(leaf.closing_debit, ".2f"),
                    "closing_credit": format(leaf.closing_credit, ".2f"),
                    "opening_debit": format(leaf.closing_debit, ".2f"),
                    "opening_credit": format(leaf.closing_credit, ".2f"),
                    "source_anchor": {"row": leaf.row, "region": f"{sheet_name}!{leaf.row}"},
                })
        balances.append({
            "account_code": root.account_code,
            "account_name": root.account_name,
            "closing_debit": format(root.closing_debit, ".2f"),
            "closing_credit": format(root.closing_credit, ".2f"),
            "opening_debit": format(root.closing_debit, ".2f"),
            "opening_credit": format(root.closing_credit, ".2f"),
            "source_anchor": {"row": root.row, "region": f"{sheet_name}!{root.row}"},
            "requires_auxiliary": needs_auxiliary,
            "auxiliary": auxiliary,
        })
    return {
        "prior_period": prior_period,
        "close_reference": close_reference,
        "balance_source": balance_source,
        "close_source": close_source,
        "currency": "CNY",
        "completeness_confirmed": True,
        "balances": balances,
    }
