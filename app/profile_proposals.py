"""版式提案：看一份陌生表格的结构，提出"字段在第几列"的候选，并用内生真值自校验。

与别名表的根本区别：这里不匹配列名，而是读**列的内容形态**——哪一列能解析成日期、
哪些列是金额、哪一列是余额、哪一列的取值是少量固定方向词。收付方向不靠列名猜测，
而是用余额连续性（余额ₜ = 余额ₜ₋₁ − 支出 + 收入）反推，算不通就不出提案。

提案永远是候选：confidence 与 evidence 一并返回，由人工确认后才成为版式。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from app.source_profiles import DEFAULT_NULL_TOKENS, ProfileMapping, normalize_label
from app.tabular import date_value, money_value

PROPOSER_VERSION = "profile-proposer-v1"

SAMPLE_ROWS = 60
# 少于这么多次余额比对，就不足以单独定方向：仍然出提案，但置信度按比例压低，
# 由人工卡片确认后才成为版式。
FULL_EVIDENCE_TRANSITIONS = 8
MIN_TRANSITIONS = 2


def confidence_from(rate: float, checked: int) -> int:
    """置信度同时反映"算得准"和"算了几次"。3 行的文件不该拿到 95 分。"""
    if checked < MIN_TRANSITIONS:
        return 0
    return int(round(rate * 100 * min(1.0, checked / FULL_EVIDENCE_TRANSITIONS)))
# 方向词表用于"识别某列是不是方向列"，不用于判断哪个方向是收、哪个是支——
# 那件事只由余额连续性决定。
DIRECTION_VOCABULARY = {
    "收入", "支出", "来账", "往账", "收", "付", "借", "贷", "进", "出",
    "转入", "转出", "收款", "付款", "存入", "支取", "credit", "debit",
}
BALANCE_HINTS = {"余额", "账户余额", "交易后余额", "当前余额", "afterbalance"}


class MappingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: StrictStr = Field(pattern="^(PROPOSAL|ABSTAIN)$")
    header_row: StrictInt = 0
    mapping: Optional[ProfileMapping] = None
    confidence: StrictInt = 0
    label_hint: StrictStr = ""
    evidence: list[StrictStr] = Field(default_factory=list)
    reason: StrictStr = ""


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text in DEFAULT_NULL_TOKENS


SUMMARY_TOKENS = {"合计", "总计", "小计", "本页合计", "期初余额", "期末余额",
                  "总收入笔数", "总支出笔数", "交易笔数"}


def _is_reference_row(values: list[Any]) -> bool:
    """页脚合计与小结行不是交易，不能参与列形态判断与余额连续性校验。"""
    texts = [str(v).strip() for v in values if not _is_blank(v)]
    return any(t in SUMMARY_TOKENS for t in texts[:4])


def _parses(value: Any, parser) -> bool:
    if _is_blank(value):
        return False
    try:
        parser(value)
        return True
    except (ValueError, ArithmeticError):
        return False


def _column_stats(rows: list[list[Any]], index: int) -> dict[str, Any]:
    values = [row[index] if index < len(row) else None for row in rows]
    filled = [v for v in values if not _is_blank(v)]
    total = max(len(values), 1)
    money = [v for v in filled if _parses(v, money_value)]
    return {
        "index": index,
        "filled": len(filled),
        "fill_ratio": len(filled) / total,
        "date_ratio": sum(1 for v in filled if _parses(v, date_value)) / max(len(filled), 1),
        "money_ratio": len(money) / max(len(filled), 1),
        "money_count": len(money),
        "negatives": sum(1 for v in money if Decimal(money_value(v)) < 0),
        "distinct": {str(v).strip() for v in filled},
        "avg_len": sum(len(str(v).strip()) for v in filled) / max(len(filled), 1),
        "values": values,
    }


def _find_header_row(rows: list[dict[str, Any]], limit: int = 20) -> int:
    """表头行 = 前若干行里，短文本单元格最多、且下方还有数据的那一行。"""
    best, best_score = -1, 0
    for position, row in enumerate(rows[:limit]):
        labels = [str(v).strip() for v in row["values"] if not _is_blank(v)]
        if len(labels) < 3 or position >= len(rows) - 1:
            continue
        short_text = [x for x in labels if 1 <= len(x) <= 24 and not _parses(x, money_value)]
        score = len(short_text)
        if score > best_score:
            best, best_score = position, score
    return best


def _pick_balance(stats: list[dict[str, Any]], labels: list[str], money_columns: list[int]) -> Optional[int]:
    """余额列：列名有提示，或该列几乎每行都有值而其他金额列是稀疏的。"""
    for index in money_columns:
        if any(hint in normalize_label(labels[index]) for hint in BALANCE_HINTS):
            return index
    dense = [i for i in money_columns if stats[i]["fill_ratio"] > 0.95]
    return dense[0] if len(dense) == 1 else None


def _verify_by_balance(rows: list[list[Any]], balance: int, expense: int, income: int,
                       timing: str = "AFTER") -> float:
    """用余额连续性验证收付两列的归属，返回通过率。

    timing=AFTER  余额是交易后余额：余额ₜ = 余额ₜ₋₁ − 支出ₜ + 收入ₜ
    timing=BEFORE 余额是交易前余额：余额ₜ = 余额ₜ₋₁ − 支出ₜ₋₁ + 收入ₜ₋₁
    """
    checked = passed = 0
    previous = None
    previous_row = None
    for row in rows:
        def cell(index, source=None):
            source = row if source is None else source
            return source[index] if index < len(source) else None
        if not _parses(cell(balance), money_value):
            previous, previous_row = None, None
            continue
        current = Decimal(money_value(cell(balance)))
        movement_row = row if timing == "AFTER" else previous_row
        if previous is not None and movement_row is not None:
            out_raw, in_raw = cell(expense, movement_row), cell(income, movement_row)
            out = Decimal(money_value(out_raw)) if _parses(out_raw, money_value) else Decimal(0)
            inn = Decimal(money_value(in_raw)) if _parses(in_raw, money_value) else Decimal(0)
            checked += 1
            if abs((previous - abs(out) + abs(inn)) - current) <= Decimal("0.01"):
                passed += 1
        previous, previous_row = current, row
    return (passed / checked if checked else 0.0), checked


def _verify_single(rows: list[list[Any]], balance: int, amount: int,
                   direction: Optional[int], expense_words: set[str]) -> float:
    checked = passed = 0
    previous = None
    for row in rows:
        def cell(index):
            return row[index] if index is not None and index < len(row) else None
        if not _parses(cell(balance), money_value):
            previous = None
            continue
        current = Decimal(money_value(cell(balance)))
        if previous is not None and _parses(cell(amount), money_value):
            value = Decimal(money_value(cell(amount)))
            if direction is None:
                delta = value  # 带符号单列：正数进、负数出
            else:
                token = str(cell(direction) or "").strip()
                delta = -abs(value) if token in expense_words else abs(value)
            checked += 1
            if abs((previous + delta) - current) <= Decimal("0.01"):
                passed += 1
        previous = current
    return (passed / checked if checked else 0.0), checked


def _chronological(body: list[list[Any]], date_column: int) -> tuple[list[list[Any]], str]:
    """把样本按时间正序排列后再做余额连续性校验。

    很多网银导出是倒序（最新一笔在最前）。不先纠正时序就验余额，算术仍然成立，
    但支出与收入会被整体标反 —— 这是一种不会报错的错误，必须在这里挡住。
    """
    ascending = descending = 0
    previous = None
    for row in body:
        cell = row[date_column] if date_column < len(row) else None
        if not _parses(cell, date_value):
            continue
        current = date_value(cell)
        if previous is not None:
            if current > previous:
                ascending += 1
            elif current < previous:
                descending += 1
        previous = current
    if descending > ascending:
        return list(reversed(body)), "DESC"
    return body, "ASC"


def propose_mapping(sheet: dict[str, Any], document_kind: str) -> MappingProposal:
    """只支持银行流水；其余资料类型暂不提案，明确弃权而不是给个不可靠的猜测。"""
    if document_kind != "bank_statement":
        return MappingProposal(outcome="ABSTAIN", reason="当前只对银行流水提案版式")

    rows = [r for r in sheet["rows"] if any(not _is_blank(v) for v in r["values"])]
    header_position = _find_header_row(rows)
    if header_position < 0:
        return MappingProposal(outcome="ABSTAIN", reason="未能定位表头行")

    header = rows[header_position]
    # 即使最终弃权也要带回表头行：上层要用它算指纹，
    # 否则会退化成拿标题行做指纹，把企业名称这类业务值混进去。
    def abstain(reason: str) -> MappingProposal:
        return MappingProposal(outcome="ABSTAIN", header_row=header["row"], reason=reason)

    labels = [str(v or "").strip() for v in header["values"]]
    body = [r["values"] for r in rows[header_position + 1:] if not _is_reference_row(r["values"])][:SAMPLE_ROWS]
    if len(body) < 2:
        return abstain("表头之下数据不足，无法判断列形态")

    width = max((len(r) for r in body), default=0)
    stats = [_column_stats(body, i) for i in range(width)]

    date_columns = [s["index"] for s in stats if s["filled"] and s["date_ratio"] >= 0.8]
    if not date_columns:
        return abstain("没有任何一列能稳定解析为日期")
    date_column = max(date_columns, key=lambda i: (stats[i]["date_ratio"], stats[i]["fill_ratio"]))

    money_columns = [s["index"] for s in stats
                     if s["index"] != date_column and s["money_count"] >= 2 and s["money_ratio"] >= 0.9]
    # 对侧金额列在样本里可能只出现一两次（例如整月只有一笔收入），不能因稀疏被排除。
    sparse_amounts = [s["index"] for s in stats
                      if s["index"] != date_column and s["index"] not in money_columns
                      and s["money_count"] >= 1 and s["money_ratio"] >= 0.9]
    balance = _pick_balance(stats, labels, money_columns)
    if balance is None:
        return abstain("未能确定余额列，无法用余额连续性验证收付方向")
    amount_columns = [i for i in money_columns if i != balance]
    if not amount_columns:
        return abstain("除余额外没有金额列")

    body, row_order = _chronological(body, date_column)
    evidence = [f"表头行 {header['row']}", f"日期列 {labels[date_column] or date_column}",
                f"余额列 {labels[balance] or balance}",
                "行序 " + ("倒序（已按时间正序校验）" if row_order == "DESC" else "正序")]

    # ① 借贷分列：两列金额，用余额连续性判定谁是支出谁是收入。
    pair_candidates = amount_columns + [i for i in sparse_amounts if i != balance]
    if len(pair_candidates) >= 2:
        scored = []
        for left in pair_candidates:
            for right in pair_candidates:
                if left == right:
                    continue
                for timing in ("AFTER", "BEFORE"):
                    rate, checked = _verify_by_balance(body, balance, left, right, timing)
                    scored.append((rate, checked, left, right, timing))
        scored.sort(key=lambda item: -item[0])
        best = scored[0] if scored else None
        runner_up = next((s[0] for s in scored[1:] if {s[2], s[3]} != {best[2], best[3]}), 0.0) if best else 0.0
        # 必须既足够准，又明显优于其他列组合；两者都满足才敢定方向。
        if best and best[0] >= 0.85 and best[0] - runner_up >= 0.15 and best[1] >= MIN_TRANSITIONS:
            rate, checked, expense, income, timing = best
            mapping = ProfileMapping(
                header_row=header["row"],
                fields={"transaction_date": [date_column], "expense": [expense],
                        "income": [income], "balance": [balance],
                        **_text_fields(stats, labels, {date_column, balance, expense, income})},
                amount_model="TWO_COLUMN", balance_timing=timing,
                notes="收付归属由余额连续性判定",
            )
            evidence.append(f"支出列 {labels[expense] or expense}／收入列 {labels[income] or income}")
            evidence.append(f"余额连续性通过率 {rate:.0%}（比对 {checked} 次）"
                            + ("，余额为交易前余额" if timing == "BEFORE" else ""))
            return MappingProposal(outcome="PROPOSAL", header_row=header["row"], mapping=mapping,
                                   confidence=min(95, confidence_from(rate, checked)),
                                   label_hint=_label_hint(sheet, labels), evidence=evidence)

    # ② 单列金额：带符号，或配一列方向词。
    amount = max(amount_columns, key=lambda i: stats[i]["fill_ratio"])
    signed_rate, signed_checked = _verify_single(body, balance, amount, None, set())
    if signed_rate >= 0.9 and signed_checked >= MIN_TRANSITIONS:
        mapping = ProfileMapping(
            header_row=header["row"],
            fields={"transaction_date": [date_column], "amount": [amount], "balance": [balance],
                    **_text_fields(stats, labels, {date_column, balance, amount})},
            amount_model="SIGNED_SINGLE", notes="单列带符号金额，方向由符号判定")
        evidence.append(f"金额列 {labels[amount] or amount}（带符号）")
        evidence.append(f"余额连续性通过率 {signed_rate:.0%}（比对 {signed_checked} 次）")
        return MappingProposal(outcome="PROPOSAL", header_row=header["row"], mapping=mapping,
                               confidence=min(95, confidence_from(signed_rate, signed_checked)),
                               label_hint=_label_hint(sheet, labels), evidence=evidence)

    for candidate in stats:
        tokens = candidate["distinct"]
        if candidate["index"] in {date_column, balance, amount} or not tokens or len(tokens) > 6:
            continue
        if not all(normalize_label(t) in DIRECTION_VOCABULARY or len(t) <= 4 for t in tokens):
            continue
        for expense_words in _partitions(tokens):
            rate, checked = _verify_single(body, balance, amount, candidate["index"], expense_words)
            if rate >= 0.9 and checked >= MIN_TRANSITIONS:
                income_words = sorted(tokens - expense_words)
                mapping = ProfileMapping(
                    header_row=header["row"],
                    fields={"transaction_date": [date_column], "amount": [amount],
                            "direction": [candidate["index"]], "balance": [balance],
                            **_text_fields(stats, labels, {date_column, balance, amount, candidate["index"]})},
                    amount_model="DIRECTION_SINGLE",
                    direction_expense=sorted(expense_words), direction_income=income_words,
                    notes="单列金额配方向列，方向取值由余额连续性判定")
                evidence.append(f"方向列 {labels[candidate['index']] or candidate['index']}："
                                f"支出={sorted(expense_words)} 收入={income_words}")
                evidence.append(f"余额连续性通过率 {rate:.0%}（比对 {checked} 次）")
                return MappingProposal(outcome="PROPOSAL", header_row=header["row"], mapping=mapping,
                                       confidence=min(95, confidence_from(rate, checked)),
                                       label_hint=_label_hint(sheet, labels), evidence=evidence)

    return abstain("收付方向无法通过余额连续性验证，不出提案")


def _partitions(tokens: set[str]) -> list[set[str]]:
    """方向词只有少数几个，枚举"哪些算支出"的全部非平凡划分。"""
    items = sorted(tokens)
    results = []
    for mask in range(1, 2 ** len(items) - 1):
        results.append({items[i] for i in range(len(items)) if mask >> i & 1})
    return results


def _text_fields(stats: list[dict[str, Any]], labels: list[str], used: set[int]) -> dict[str, list[int]]:
    """对方、摘要、附言：按内容形态挑，挑不出就留空而不是硬塞一列。"""
    hints = {"counterparty": ("对方户名", "对手方名称", "对方名称", "对方姓名", "对方单位", "收款人名称", "付款人名称"),
             "counterparty_account": ("对方账号", "对方账户", "收款人账号", "付款人账号"),
             "summary": ("摘要", "交易类型", "业务类型", "交易种类"),
             "note": ("附言", "用途", "备注", "交易附言")}
    chosen: dict[str, list[int]] = {}
    for field, names in hints.items():
        wanted = {normalize_label(n) for n in names}
        for index, label in enumerate(labels):
            if index in used or index in {v[0] for v in chosen.values()}:
                continue
            if normalize_label(label) in wanted:
                chosen[field] = [index]
                break
    return chosen


def _label_hint(sheet: dict[str, Any], labels: list[str]) -> str:
    name = str(sheet.get("name") or "").strip()
    head = "／".join(x for x in labels[:4] if x)
    return f"{name}｜{head}"[:120]
