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
        # 有下级就保留下级，不按科目类别筛。按前缀挑"哪些算辅助核算"会丢信息：
        # 银行存款的下级是各个银行账户，正是要和对账单期初对上的那个数。
        detail = [leaf for leaf in leaves(root) if leaf.account_code != root.account_code]
        auxiliary = []
        if detail:
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
            "requires_auxiliary": bool(detail),
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


def as_extracted(sheet: dict[str, Any], *, period: str, sheet_name: str = "余额表") -> dict[str, Any]:
    """产出与 opening_balance 别名路径同形的提取结果。

    账套导出的余额表是两行表头（期初／本期发生／期末，各自再分借贷），
    "借方金额"在同一行里出现三次，逐列名匹配的别名表接不住。这里按
    科目树解析，但记录形状保持一致，基线比对逻辑不需要分叉。
    """
    roots = parse_balance_sheet(sheet)
    debit, credit = trial_balance(roots)
    records: list[dict[str, Any]] = []
    for root in roots:
        for leaf in leaves(root):
            detail = leaf.account_code != root.account_code
            anchor = {"row": leaf.row, "region": f"{sheet_name}!{leaf.row}"}
            records.append({
                "record_type": "OPENING_BALANCE",
                "source_anchor": anchor,
                "original_value": {"sheet": sheet_name, "row": leaf.row,
                                   "headers": ["科目编码", "科目", "期末借方", "期末贷方"],
                                   "values": [leaf.account_code, leaf.account_name,
                                              format(leaf.closing_debit, ".2f"),
                                              format(leaf.closing_credit, ".2f")],
                                   "cell_types": ["General"] * 4, "formulas": {}},
                "normalized_value": {
                    "account_code": root.account_code,
                    "account_name": root.account_name,
                    "auxiliary_key": leaf.account_name if detail else "",
                    # 必须是真布尔：下游用 bool() 判断，中文的"否"是非空字符串，
                    # 会被当成 True，把没有明细的科目全部误判成"缺辅助明细"。
                    "requires_auxiliary": detail,
                    "closing_debit": format(leaf.closing_debit, ".2f"),
                    "closing_credit": format(leaf.closing_credit, ".2f"),
                    "opening_debit": format(leaf.closing_debit, ".2f"),
                    "opening_credit": format(leaf.closing_credit, ".2f"),
                    "period": period,
                },
                "field_sources": {},
                "extraction_issues": [],
                "extraction_confidence": 1.0,
                "period_check": "PASS",
            })
    return {
        "records": records,
        "sheets": [{"sheet": sheet_name, "status": "EXTRACTED", "rows": len(records),
                    "mapping_origin": "ACCOUNT_TREE",
                    "trial_balance": {"debit": format(debit, ".2f"), "credit": format(credit, ".2f")}}],
        "errors": ([] if debit == credit
                   else [f"余额表期末试算不平衡：借 {debit}，贷 {credit}"]),
        "checks": {"overall": "PASS" if debit == credit else "REVIEW", "items": []},
    }
