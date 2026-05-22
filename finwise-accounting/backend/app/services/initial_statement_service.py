from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import pandas as pd


class InitialStatementParseError(Exception):
    pass


FIELD_ALIASES = {
    "BALANCE_SHEET": {
        "资产总计": ["资产总计"],
        "负债合计": ["负债合计"],
        "所有者权益合计": ["所有者权益合计", "所有者权益（或股东权益）合计"],
        "货币资金": ["货币资金"],
        "应收账款": ["应收账款"],
        "存货": ["存货"],
        "应付账款": ["应付账款"],
    },
    "INCOME_STATEMENT": {
        "营业收入": ["营业收入", "一、营业收入"],
        "营业成本": ["营业成本", "减：营业成本"],
        "管理费用": ["管理费用"],
        "营业利润": ["营业利润", "三、营业利润"],
        "净利润": ["净利润", "四、净利润"],
    },
}

REQUIRED_FIELDS = {
    "BALANCE_SHEET": ["资产总计", "负债合计", "所有者权益合计"],
    "INCOME_STATEMENT": ["营业收入", "净利润"],
}


def parse_initial_statement(path: Path, *, statement_type: str) -> dict:
    normalized_type = statement_type.upper()
    if normalized_type not in FIELD_ALIASES:
        raise InitialStatementParseError("statement_type must be BALANCE_SHEET or INCOME_STATEMENT.")

    frame = pd.read_excel(path, header=None)
    data = {}
    for field_name, aliases in FIELD_ALIASES[normalized_type].items():
        value = _find_field_value(frame, aliases, statement_type=normalized_type)
        if value is not None:
            data[field_name] = _format_decimal(value)

    missing_fields = [field for field in REQUIRED_FIELDS[normalized_type] if field not in data]
    return {
        "statement_type": normalized_type,
        "data": data,
        "missing_fields": missing_fields,
    }


def _find_field_value(frame: pd.DataFrame, aliases: list[str], *, statement_type: str) -> Decimal | None:
    for row_index in range(len(frame.index)):
        for column_index in range(len(frame.columns)):
            cell_text = _normalize_text(frame.iat[row_index, column_index])
            if not cell_text:
                continue
            if any(alias in cell_text for alias in aliases):
                value = _preferred_numeric_value_on_row(frame, row_index, column_index + 1, statement_type=statement_type)
                if value is not None:
                    return value
    return None


def _preferred_numeric_value_on_row(
    frame: pd.DataFrame,
    row_index: int,
    start_column: int,
    *,
    statement_type: str,
) -> Decimal | None:
    numeric_candidates = []
    for column_index in range(start_column, len(frame.columns)):
        value = _to_decimal(frame.iat[row_index, column_index])
        if value is not None:
            numeric_candidates.append((column_index, value))
    if not numeric_candidates:
        return None

    preferred_headers = ("期末余额",) if statement_type == "BALANCE_SHEET" else ("本月金额", "本期金额")
    for column_index, value in numeric_candidates:
        header_text = _column_header_text(frame, row_index, column_index)
        if any(header in header_text for header in preferred_headers):
            return value

    if len(numeric_candidates) > 1 and _looks_like_line_number(numeric_candidates[0][1]):
        return numeric_candidates[1][1]

    non_line_number_candidates = [
        (column_index, value)
        for column_index, value in numeric_candidates
        if "行次" not in _column_header_text(frame, row_index, column_index)
    ]
    if non_line_number_candidates:
        return non_line_number_candidates[0][1]
    return numeric_candidates[0][1]


def _looks_like_line_number(value: Decimal) -> bool:
    return value == value.to_integral_value() and Decimal("0") <= value <= Decimal("200")


def _column_header_text(frame: pd.DataFrame, row_index: int, column_index: int) -> str:
    header_values = []
    for header_row in range(max(0, row_index - 8), row_index):
        header_values.append(_normalize_text(frame.iat[header_row, column_index]))
    return "".join(header_values)


def _normalize_text(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).replace(" ", "").replace("\u3000", "").strip()


def _to_decimal(value) -> Decimal | None:
    if pd.isna(value):
        return None
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        decimal_value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not decimal_value.is_finite():
        return None
    return decimal_value


def _format_decimal(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"
