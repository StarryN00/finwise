"""
Utilities for importing enterprise metadata and bank statement rows from
accountant-provided Excel/CSV files.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ENTERPRISE_NAME_KEYS = {"企业名称", "公司名称", "账户名称", "户名"}
TAX_NUMBER_KEYS = {"纳税人识别号", "统一社会信用代码", "税号"}
BUSINESS_SCOPE_KEYS = {"经营范围"}

DATE_KEYS = {"交易日期", "交易时间", "日期", "记账日期"}
SUMMARY_KEYS = {"摘要", "交易说明", "用途", "用途/附言", "用途附言", "摘要说明", "备注"}
DEBIT_KEYS = {"借方", "借方金额", "借方发生额（支取）", "支出金额", "借记金额", "借方发生额"}
CREDIT_KEYS = {"贷方", "贷方金额", "贷方发生额（收入）", "收入金额", "贷记金额", "贷方发生额"}
AMOUNT_KEYS = {"交易金额", "发生额", "金额", "Trade Amount"}
BALANCE_KEYS = {"余额", "账户余额", "当前余额", "交易后余额", "After-transaction balance"}
COUNTERPARTY_KEYS = {"对方户名", "对手方名称", "对方账户名"}


@dataclass
class EnterpriseMetadata:
    name: str | None = None
    tax_number: str | None = None
    business_scope: str | None = None


def read_table(path: Path) -> pd.DataFrame:
    ext = path.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path, header=None, dtype=object, encoding="utf-8-sig")
    return pd.read_excel(path, header=None, dtype=object)


def extract_enterprise_metadata(path: Path, fallback_name: str | None = None) -> EnterpriseMetadata:
    df = read_table(path)
    metadata = EnterpriseMetadata(name=fallback_name)

    for _, row in df.head(20).iterrows():
        values = [clean_text(v) for v in row.tolist()]
        values = [v for v in values if v]
        if len(values) < 2:
            continue

        key = values[0].rstrip(":：")
        value = values[1]
        if key in ENTERPRISE_NAME_KEYS and value:
            metadata.name = value
        elif key in TAX_NUMBER_KEYS and value:
            metadata.tax_number = value
        elif key in BUSINESS_SCOPE_KEYS and value:
            metadata.business_scope = value

    return metadata


def parse_bank_statement_file(path: Path, enterprise_id: str, import_batch_id: str) -> list[dict[str, Any]]:
    df = read_table(path)
    header_index = find_header_row(df)
    if header_index is None:
        return []

    headers = [clean_text(v) or f"col_{i}" for i, v in enumerate(df.iloc[header_index].tolist())]
    data = df.iloc[header_index + 1 :].copy()
    data.columns = headers
    data = data.dropna(how="all")

    date_col = find_column(headers, DATE_KEYS)
    summary_col = find_column(headers, SUMMARY_KEYS)
    debit_col = find_column(headers, DEBIT_KEYS)
    credit_col = find_column(headers, CREDIT_KEYS)
    amount_col = find_column(headers, AMOUNT_KEYS)
    balance_col = find_column(headers, BALANCE_KEYS)
    counterparty_col = find_column(headers, COUNTERPARTY_KEYS)

    if not date_col or not summary_col or (not debit_col and not credit_col and not amount_col):
        return []

    transactions: list[dict[str, Any]] = []
    for _, row in data.iterrows():
        tx_date = parse_date(row.get(date_col))
        if not tx_date:
            continue

        summary = clean_text(row.get(summary_col)) or ""
        counterparty = clean_text(row.get(counterparty_col)) if counterparty_col else ""
        if counterparty and counterparty not in summary:
            summary = f"{summary} {counterparty}".strip()

        debit = parse_money(row.get(debit_col)) if debit_col else None
        credit = parse_money(row.get(credit_col)) if credit_col else None
        amount = parse_money(row.get(amount_col)) if amount_col else None
        balance = parse_money(row.get(balance_col)) if balance_col else None
        debit = abs(debit) if debit is not None else None
        credit = abs(credit) if credit is not None else None
        if amount is not None and not debit and not credit:
            if amount < 0:
                debit = abs(amount)
            elif amount > 0:
                credit = amount

        if not debit and not credit:
            continue

        transactions.append(
            {
                "enterprise_id": enterprise_id,
                "transaction_date": tx_date.isoformat(),
                "summary": summary or "银行流水",
                "debit_amount": float(debit) if debit else None,
                "credit_amount": float(credit) if credit else None,
                "balance": float(balance) if balance is not None else None,
                "confidence": 1.0,
                "status": "CONFIRMED",
                "import_batch_id": import_batch_id,
            }
        )

    return transactions


def infer_period_from_filename(path: Path, default_year: int = 2026) -> tuple[int | None, int | None]:
    name = path.stem
    year_match = re.search(r"(20\d{2})", name)
    year = int(year_match.group(1)) if year_match else default_year

    month_match = re.search(r"(?<!\d)(1[0-2]|0?[1-9])月", name)
    if month_match:
        return year, int(month_match.group(1))
    return year, None


def find_header_row(df: pd.DataFrame) -> int | None:
    for idx, row in df.iterrows():
        values = {clean_text(v) for v in row.tolist() if clean_text(v)}
        has_date = bool(find_column(values, DATE_KEYS))
        has_summary = bool(find_column(values, SUMMARY_KEYS))
        has_amount = any(
            find_column(values, candidates)
            for candidates in (DEBIT_KEYS, CREDIT_KEYS, AMOUNT_KEYS)
        )
        if has_date and has_summary and has_amount:
            return int(idx)
    return None


def find_column(headers: Iterable[str], candidates: set[str]) -> str | None:
    for header in headers:
        if header in candidates:
            return header
    for header in headers:
        if any(candidate in header for candidate in candidates):
            return header
    return None


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def parse_money(value: Any) -> Decimal | None:
    text = clean_text(value)
    if not text or text in {"-", "--"}:
        return None
    text = text.replace(",", "").replace("￥", "").replace("¥", "")
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return amount if amount != 0 else None


def parse_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    text = clean_text(value)
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()
