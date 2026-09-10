"""Pure, full-extraction bank/invoice checks; no filtering or record rewriting.

MATCH attests only the comparisons described here, not source completeness,
account identity, human approval or eligibility for posting. Call before period
filtering. Monetary outputs are exact decimal strings, never display-rounded.
"""
from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext
import re
import math


VERSION = "reconcile-v1"
BANK_TYPES = frozenset({"PAYMENT", "RECEIPT", "BANK_TRANSACTION"})


def _precision(numbers, count):
    return max(28, max(n.adjusted() for n in numbers) - min(n.as_tuple().exponent for n in numbers)
               + len(str(count + 1)) + 3) if numbers else 28


def _float_representation_only(raw, computed):
    # Only a numeric float declaration can carry binary representation noise.
    # Never round strings/Decimals, normalized facts or a genuine cent difference.
    if not isinstance(raw, float) or not math.isfinite(raw) or computed is None:
        return False
    if computed != computed.quantize(Decimal(".01")):
        return False
    difference = abs(Decimal(str(raw)) - computed)
    return 0 < difference <= min(Decimal(str(math.ulp(raw))) * 2, Decimal("0.000000001"))


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    text = str(value).strip()
    if "," in text:
        if not re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", text):
            return None
        text = text.replace(",", "")
    try:
        number = Decimal(text)
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def _item(code, status, message, regions=(), declared=None, computed=None):
    return {"code": code, "status": status, "message": message,
            "source_regions": list(dict.fromkeys(r for r in regions if r)),
            "declared": declared, "computed": computed}


def _location(record):
    original = record.get("original_value") or {}
    anchor = record.get("source_anchor") or {}
    region = anchor.get("region") or ""
    sheet = original.get("sheet")
    if not sheet and "!" in region:
        sheet = region.rsplit("!", 1)[0]
    return sheet, region


def _totals(sheet, references, rows, scope_known):
    """The existing BANK_TOTAL_VALUES contract declares one whole-sheet total."""
    declarations = [r for r in references if r.get("reason") == "BANK_TOTAL_VALUES"]
    if len(declarations) != 1:
        message = ("未找到四列银行自报合计，无法验证。" if not declarations else
                   "存在多组银行合计，无法确定整表或分段范围，未混用对账。")
        return [_item("BANK_TOTAL_SCOPE", "NOT_AVAILABLE", f"{sheet}：{message}")], False
    reference = declarations[0]
    row = reference.get("row")
    values = reference.get("values") or []
    regions = [f"{sheet}!A{row}:D{row}"] if row else []
    regions.extend(r["region"] for r in rows)
    known = (scope_known and bool(rows) and bool(row) and len(values) >= 4
             and not any(v not in (None, "") for v in values[4:])
             and all(r["region"] for r in rows))
    items = []
    measures = (("INCOME_COUNT", "收入笔数", "income", 0, True),
                ("INCOME_AMOUNT", "收入金额", "income", 1, False),
                ("EXPENSE_COUNT", "支出笔数", "expense", 2, True),
                ("EXPENSE_AMOUNT", "支出金额", "expense", 3, False))
    for code, label, field, column, count in measures:
        declared = _decimal(values[column]) if len(values) > column else None
        amounts = [r[field] for r in rows]
        available = (known and declared is not None and declared >= 0
                     and (not count or declared == declared.to_integral_value())
                     and all(v is not None and v >= 0 for v in amounts))
        computed = None
        if available:
            computed = Decimal(sum(v > 0 for v in amounts)) if count else sum(amounts, Decimal(0))
        floating = not count and computed is not None and _float_representation_only(values[column], computed)
        status = ("NOT_AVAILABLE" if computed is None else
                  "MATCH" if declared == computed or floating else "MISMATCH")
        message = (f"{sheet}：{label}缺少明确范围、来源或有效数值，无法验证。" if computed is None else
                   f"{sheet}：全表{label}声明 {declared}，计算 {computed}，"
                   + ("一致。" if status == "MATCH" else "不一致，请核查提取及原件。"))
        item = _item("BANK_TOTAL_" + code, status, message, regions,
                     str(declared) if declared is not None else None,
                     str(computed) if computed is not None else None)
        if floating:
            item["comparison"] = "FLOAT_REPRESENTATION_ONLY"
            item["message"] += "仅原始浮点表示尾差；保留声明原值，未放宽分钱差异。"
        items.append(item)
    return items, all(i["status"] == "MATCH" for i in items)


def _balance(rows, scope_known):
    regions = [r["region"] for r in rows]
    label = rows[0]["sheet"] or "来源未定位"
    if (not scope_known or len(rows) < 2 or
            any(not r["region"] or any(r[f] is None for f in ("balance", "income", "expense"))
                for r in rows)):
        return _item("BANK_BALANCE_CHAIN", "NOT_AVAILABLE",
                     f"{label}：缺少连续余额、收支、来源或明确账户范围，无法验证余额链；未跳过缺失行。",
                     regions)
    failures = {}
    for direction, ordered in (("FORWARD", rows), ("REVERSE", list(reversed(rows)))):
        for previous, current in zip(ordered, ordered[1:]):
            expected = previous["balance"] + current["income"] - current["expense"]
            if expected != current["balance"]:
                failures[direction] = {"declared": str(current["balance"]), "computed": str(expected),
                                       "source_regions": [previous["region"], current["region"]]}
                break
    valid = [d for d in ("FORWARD", "REVERSE") if d not in failures]
    if valid:
        order = "正序" if valid == ["FORWARD"] else "倒序" if valid == ["REVERSE"] else "正反序均"
        return _item("BANK_BALANCE_CHAIN", "MATCH",
                     f"{label}：{order}满足相邻余额递推；无独立期初锚点，开头是否漏读无法验证。",
                     regions, None, {"valid_orders": valid, "transitions": len(rows) - 1})
    return _item("BANK_BALANCE_CHAIN", "MISMATCH",
                 f"{label}：正序、倒序均有余额断点，请核查收支方向、漏行或多余行。",
                 [region for failure in failures.values() for region in failure["source_regions"]],
                 {d: f["declared"] for d, f in failures.items()},
                 {d: {"balance": f["computed"], "source_regions": f["source_regions"]}
                  for d, f in failures.items()})


def _prefix(rows):
    """Linear prefix-only probe, not arbitrary subset/interval matching."""
    items = []
    for field, label in (("income", "收入"), ("expense", "支出")):
        total, contributors = Decimal(0), 0
        first = None
        for index, row in enumerate(rows):
            value = row[field]
            if value is None:
                break  # An unknown amount cannot silently become a zero.
            if contributors >= 2 and total != 0 and value == total:
                items.append(_item("ARITHMETIC_TOTAL_PROBE", "SUSPECT",
                                   f"{row['sheet'] or '来源未定位'}：本行{label}等于此前连续明细{label}之和，"
                                   "仅为疑似汇总，不删除、不改写任何记录。",
                                   [first, rows[index - 1]["region"], row["region"]],
                                   str(value), {"field": field, "prefix_sum": str(total),
                                                "preceding_rows": index, "nonzero_rows": contributors}))
            total += value
            if value != 0:
                contributors += 1
            if first is None:
                first = row["region"]
    return items


def _invoice_checks(extracted, kind):
    fields = (("net_amount", "净额"), ("tax", "税额"), ("invoice_total", "价税合计"))
    record_type = "INVOICE" if kind == "purchase_invoices" else "SALES_INVOICE"
    records = extracted.get("records") or []
    by_sheet, summaries = defaultdict(list), defaultdict(list)
    numbers, items, covered, identities = [], [], set(), {}
    scope_known = all(r.get("record_type") == record_type and _location(r)[0] for r in records)
    for index, record in enumerate(records):
        sheet, region = _location(record)
        by_sheet[sheet].append((index, record))
        normalized = record.get("normalized_value") or {}
        numbers.extend(n for field, _ in fields if (n := _decimal(normalized.get(field))) is not None)
        identity = normalized.get("invoice_no")
        if identity:
            if identity in identities and identities[identity][0] != sheet:
                items.append(_item("INVOICE_DUPLICATE_SHEET", "SUSPECT",
                                   "同一发票出现在不同工作表，需核对主表与汇总表关系；未合并或删除记录。",
                                   [identities[identity][1], region]))
            identities[identity] = (sheet, region)
    for summary in extracted.get("sheets") or []:
        for reference in summary.get("reference_rows") or []:
            if reference.get("reason") in {"INVOICE_TOTAL", "SUMMARY_REFERENCE"}:
                values = reference.get("values") or []
                label = re.sub(r"\s+", "", str(next((v for v in values if v not in (None, "")), ""))).rstrip(":：")
                # Page/section subtotals and reference-only sheets are not full-sheet anchors.
                if label in {"合计", "合计行", "总计"} and summary.get("status") not in {"REFERENCE", "REFERENCE_ONLY"}:
                    summaries[summary.get("sheet")].append(reference)
                    numbers.extend(n for v in values if (n := _decimal(v)) is not None)
    missing_sheet = False
    with localcontext() as context:
        context.prec = _precision(numbers, len(records))
        for sheet in dict.fromkeys([*by_sheet, *summaries]):
            rows, declarations = by_sheet[sheet], summaries[sheet]
            if not rows and declarations:
                missing_sheet = True
            declaration = declarations[0] if len(declarations) == 1 else {}
            declared_row = declaration.get("row")
            values = declaration.get("values") or []
            results = []
            for field, label in fields:
                columns, regions, amounts = set(), [], []
                available = bool(scope_known and sheet and rows and declared_row)
                for _, record in rows:
                    source = (record.get("field_sources") or {}).get(field) or {}
                    region = source.get("region") or ""
                    origin_sheet, _, cell = region.rpartition("!")
                    match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", cell)
                    if not match or origin_sheet != sheet or int(match[2]) == declared_row or source.get("formula"):
                        available = False
                    else:
                        columns.add(match[1])
                    regions.append(region)
                    amounts.append(_decimal((record.get("normalized_value") or {}).get(field)))
                available = available and len(columns) == 1 and all(n is not None for n in amounts)
                raw, declared, computed = None, None, None
                if len(columns) == 1 and declared_row:
                    column = next(iter(columns))
                    offset = 0
                    for char in column:
                        offset = offset * 26 + ord(char) - 64
                    raw = values[offset - 1] if offset <= len(values) else None
                    declared = _decimal(raw)
                    regions.insert(0, f"{sheet}!{column}{declared_row}")
                if available and declared is not None:
                    computed = sum(amounts, Decimal(0))
                floating = _float_representation_only(raw, computed)
                status = ("NOT_AVAILABLE" if computed is None else
                          "MATCH" if declared == computed or floating else "MISMATCH")
                message = (f"{sheet}：{label}缺少唯一整表合计或一致的原始列来源，无法验证。" if computed is None else
                           f"{sheet}：全表{label}声明 {declared}，计算 {computed}，" +
                           ("一致。" if status == "MATCH" else "不一致，请核查提取及原件。"))
                item = _item("INVOICE_TOTAL_" + field.upper(), status, message, regions,
                             str(declared) if declared is not None else None,
                             str(computed) if computed is not None else None)
                if floating:
                    item["comparison"] = "FLOAT_REPRESENTATION_ONLY"
                    item["message"] += "仅原始浮点表示尾差；保留声明原值，未放宽分钱差异。"
                results.append(item)
            items.extend(results)
            if all(item["status"] == "MATCH" for item in results):
                covered.update(index for index, _ in rows)
    if not items:
        items.append(_item("INVOICE_TOTAL_SCOPE", "NOT_AVAILABLE", "无可定位发票明细或整表合计，无法验证。"))
    overall = ("REVIEW" if any(i["status"] in {"MISMATCH", "SUSPECT"} for i in items) else
               "MATCH" if records and len(covered) == len(records) and not missing_sheet else "UNATTESTED")
    return {"version": VERSION, "items": items, "overall": overall}


def reconcile(extracted, kind):
    """Return ``{version, items, overall}`` without mutating ``extracted``.

    Input is tabular's complete records/sheets(reference_rows), not a period
    subset. Supports bank_statement, purchase_invoices and sales_invoices.
    Invoices compare net/tax/total against one explicitly whole-sheet reference
    using single-cell field_sources (never inferred total columns or tax rates).
    BANK_TOTAL_VALUES means a
    single four-column *sheet* total; repeated totals have ambiguous scope.
    Counts use positive direction amounts; negative direction columns abstain.
    Balance/probe groups use source sheet + normalized bank_account_ref, in
    original extraction order. A wholly unbound sheet is one mathematical
    stream, never an assertion that its bank account identity is verified.

    REVIEW means mismatch or suspicion; MATCH requires every input bank row
    covered by a complete four-column match or a complete balance chain.
    Otherwise UNATTESTED (not a reconciliation failure). Absent optional checks
    do not undo other attestation. Existing extracted.checks are not trusted.
    No result grants business approval or posting eligibility.
    """
    if kind in {"purchase_invoices", "sales_invoices"}:
        return _invoice_checks(extracted, kind)
    if kind != "bank_statement":
        return {"version": VERSION, "items": [_item("RECONCILIATION_SCOPE", "NOT_AVAILABLE",
                "当前校验器仅核对银行流水及进销项发票，此资料类型未提供可执行对账规则。")], "overall": "UNATTESTED"}
    records = extracted.get("records") or []
    rows, by_sheet, groups = [], defaultdict(list), defaultdict(list)
    for index, record in enumerate(records):
        if record.get("record_type") not in BANK_TYPES:
            continue
        value = record.get("normalized_value") or {}
        sheet, region = _location(record)
        row = {"index": index, "sheet": sheet, "region": region,
               "account": value.get("bank_account_ref") or None,
               **{field: _decimal(value.get(field)) for field in ("income", "expense", "balance")}}
        rows.append(row)
        by_sheet[sheet].append(row)
        groups[sheet, row["account"]].append(row)
    summaries = defaultdict(list)
    for sheet in extracted.get("sheets") or []:
        summaries[sheet.get("sheet")].extend(sheet.get("reference_rows") or [])
    # Derive precision from the input span + carry digits, not caller context or
    # cell number_format. This also preserves differences below one cent.
    numbers = [r[f] for r in rows for f in ("income", "expense", "balance") if r[f] is not None]
    numbers.extend(n for refs in summaries.values() for ref in refs
                   if ref.get("reason") == "BANK_TOTAL_VALUES"
                   for v in (ref.get("values") or [])[:4] if (n := _decimal(v)) is not None)
    items, covered = [], set()
    scope_known = len(rows) == len(records) and all(r["sheet"] for r in rows)
    sheet_accounts = {sheet: {r["account"] for r in values} for sheet, values in by_sheet.items()}
    with localcontext() as context:
        context.prec = _precision(numbers, len(records))
        for sheet in dict.fromkeys([*by_sheet, *summaries]):
            sheet_rows = by_sheet[sheet]
            results, matched = _totals(sheet, summaries[sheet], sheet_rows, scope_known)
            items.extend(results)
            if matched:
                covered.update(r["index"] for r in sheet_rows)
        for (sheet, account), group in groups.items():
            accounts = sheet_accounts[sheet]
            known = bool(sheet) and not (None in accounts and len(accounts) > 1)
            result = _balance(group, known)
            items.append(result)
            if result["status"] == "MATCH":
                covered.update(r["index"] for r in group)
            if known:
                items.extend(_prefix(group))
    if not rows or len(rows) != len(records):
        items.append(_item("RECONCILIATION_SCOPE", "NOT_AVAILABLE", "存在非银行记录或无银行明细，未对这些记录作出验证。"))
    missing_declared_sheet = any(not by_sheet[sheet] and
                                 any(r.get("reason") == "BANK_TOTAL_VALUES" for r in refs)
                                 for sheet, refs in summaries.items())
    overall = ("REVIEW" if any(i["status"] in {"MISMATCH", "SUSPECT"} for i in items) else
               "MATCH" if records and len(covered) == len(records) and not missing_declared_sheet
               else "UNATTESTED")
    return {"version": VERSION, "items": items, "overall": overall}
