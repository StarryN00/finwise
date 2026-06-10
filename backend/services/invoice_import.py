"""
Utilities for importing electronic-tax-bureau invoice detail exports.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


INVOICE_NUMBER_KEYS = {"发票号码", "发票号", "数电发票号码", "数电票号码", "全电发票号码", "Invoice No"}
INVOICE_NUMBER_PRIORITY = ["数电发票号码", "全电发票号码", "数电票号码", "发票号码", "发票号", "Invoice No", "发票代码"]
INVOICE_TYPE_KEYS = {"发票类型", "票种", "发票种类"}
ISSUE_DATE_KEYS = {"开票日期", "填开日期", "发票日期", "Issue Date"}
AMOUNT_KEYS = {"金额", "不含税金额", "合计金额", "销售额", "金额(不含税)"}
TAX_AMOUNT_KEYS = {"税额", "合计税额"}
TOTAL_AMOUNT_KEYS = {"价税合计", "合计金额(含税)", "含税金额", "总金额"}
TAX_RATE_KEYS = {"税率", "征收率"}
SELLER_NAME_KEYS = {"销售方名称", "销方名称", "销方企业名称", "销方"}
SELLER_TAX_KEYS = {"销售方纳税人识别号", "销方识别号", "销方税号", "销售方税号"}
BUYER_NAME_KEYS = {"购买方名称", "购方名称", "购方企业名称", "购方"}
BUYER_TAX_KEYS = {"购买方纳税人识别号", "购方识别号", "购方税号", "购买方税号"}
ITEM_NAME_KEYS = {"商品名称", "货物或应税劳务名称", "货物或应税劳务、服务名称", "项目名称", "商品和服务税收分类编码简称"}
STATUS_KEYS = {"发票状态", "状态", "有效标志"}
DIRECTION_KEYS = {"发票方向", "方向", "进销项", "类型"}


def parse_invoice_detail_file(path: Path, enterprise: dict) -> list[dict[str, Any]]:
    df = read_table(path)
    header_index = find_header_row(df)
    if header_index is None:
        return []

    headers = [clean_text(v) or f"col_{i}" for i, v in enumerate(df.iloc[header_index].tolist())]
    data = df.iloc[header_index + 1 :].copy()
    data.columns = headers
    data = data.dropna(how="all")

    invoice_number_cols = find_columns(headers, INVOICE_NUMBER_PRIORITY)
    issue_date_col = find_column(headers, ISSUE_DATE_KEYS)
    amount_col = find_column(headers, AMOUNT_KEYS)
    tax_amount_col = find_column(headers, TAX_AMOUNT_KEYS)
    total_amount_col = find_column(headers, TOTAL_AMOUNT_KEYS)
    seller_name_col = find_column(headers, SELLER_NAME_KEYS)
    seller_tax_col = find_column(headers, SELLER_TAX_KEYS)
    buyer_name_col = find_column(headers, BUYER_NAME_KEYS)
    buyer_tax_col = find_column(headers, BUYER_TAX_KEYS)
    invoice_type_col = find_column(headers, INVOICE_TYPE_KEYS)
    tax_rate_col = find_column(headers, TAX_RATE_KEYS)
    item_name_col = find_column(headers, ITEM_NAME_KEYS)
    status_col = find_column(headers, STATUS_KEYS)
    direction_col = find_column(headers, DIRECTION_KEYS)

    if not invoice_number_cols or not issue_date_col or not (amount_col or total_amount_col):
        return []

    invoices: list[dict[str, Any]] = []
    for _, row in data.iterrows():
        invoice_number = first_row_value(row, invoice_number_cols)
        issue_date = parse_date(row.get(issue_date_col))
        if not invoice_number or not issue_date:
            continue

        amount = parse_money(row.get(amount_col)) if amount_col else None
        tax_amount = parse_money(row.get(tax_amount_col)) if tax_amount_col else None
        total_amount = parse_money(row.get(total_amount_col)) if total_amount_col else None
        amount = amount or Decimal("0")
        tax_amount = tax_amount or Decimal("0")
        total_amount = total_amount if total_amount is not None else amount + tax_amount

        seller_name = clean_text(row.get(seller_name_col)) if seller_name_col else ""
        seller_tax_number = clean_text(row.get(seller_tax_col)) if seller_tax_col else ""
        buyer_name = clean_text(row.get(buyer_name_col)) if buyer_name_col else ""
        buyer_tax_number = clean_text(row.get(buyer_tax_col)) if buyer_tax_col else ""
        direction_hint = " ".join(
            item for item in [
                path.stem,
                clean_text(row.get(direction_col)) if direction_col else "",
                clean_text(row.get(invoice_type_col)) if invoice_type_col else "",
            ] if item
        )
        direction = infer_direction(direction_hint, enterprise, seller_tax_number, buyer_tax_number)
        invoice_kind = infer_invoice_kind(clean_text(row.get(invoice_type_col)) if invoice_type_col else "")

        invoices.append(
            {
                "invoice_number": invoice_number,
                "invoice_type": invoice_kind,
                "direction": direction,
                "invoice_kind": invoice_kind,
                "issue_date": issue_date,
                "amount": amount,
                "tax_amount": tax_amount,
                "total_amount": total_amount,
                "seller_name": seller_name,
                "seller_tax_number": seller_tax_number,
                "buyer_name": buyer_name,
                "buyer_tax_number": buyer_tax_number,
                "tax_rate": parse_tax_rate(row.get(tax_rate_col)) if tax_rate_col else None,
                "item_name": clean_text(row.get(item_name_col)) if item_name_col else "",
                "invoice_status": normalize_status(clean_text(row.get(status_col)) if status_col else ""),
            }
        )

    return invoices


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, header=None, dtype=object, encoding="utf-8-sig")
    return pd.read_excel(path, header=None, dtype=object)


def find_header_row(df: pd.DataFrame) -> int | None:
    for idx, row in df.head(30).iterrows():
        values = {clean_text(v) for v in row.tolist() if clean_text(v)}
        has_invoice_number = bool(find_column(values, INVOICE_NUMBER_KEYS))
        has_date = bool(find_column(values, ISSUE_DATE_KEYS))
        has_amount = bool(find_column(values, AMOUNT_KEYS | TOTAL_AMOUNT_KEYS))
        has_party = bool(find_column(values, SELLER_NAME_KEYS | BUYER_NAME_KEYS | SELLER_TAX_KEYS | BUYER_TAX_KEYS))
        if has_invoice_number and has_date and has_amount and has_party:
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


def find_columns(headers: Iterable[str], candidates: list[str]) -> list[str]:
    matches: list[str] = []
    header_list = list(headers)
    for candidate in candidates:
        for header in header_list:
            if header == candidate or candidate in header:
                if header not in matches:
                    matches.append(header)
    return matches


def first_row_value(row: Any, columns: list[str]) -> str:
    for column in columns:
        value = clean_text(row.get(column))
        if value:
            return value
    return ""


def infer_direction(hint: str, enterprise: dict, seller_tax: str, buyer_tax: str) -> str:
    enterprise_tax = clean_text(enterprise.get("tax_number"))
    if enterprise_tax and seller_tax == enterprise_tax:
        return "SALES"
    if enterprise_tax and buyer_tax == enterprise_tax:
        return "PURCHASE"
    if any(token in hint for token in ("销项", "销货", "销售", "开具", "SALES", "OUTPUT")):
        return "SALES"
    if any(token in hint for token in ("进项", "购进", "采购", "取得", "PURCHASE", "INPUT")):
        return "PURCHASE"
    return "UNKNOWN"


def infer_invoice_kind(value: str) -> str:
    if "专用" in value or "SPECIAL" in value.upper():
        return "VAT_SPECIAL"
    if "普通" in value or "NORMAL" in value.upper():
        return "VAT_NORMAL"
    if "数电" in value or "全电" in value:
        return "DIGITAL"
    return "UNKNOWN"


def normalize_status(value: str) -> str:
    if any(token in value for token in ("作废", "红冲", "失控", "异常")):
        return "VOID"
    return "VALID"


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
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def parse_tax_rate(value: Any) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    text = text.replace("%", "")
    try:
        rate = Decimal(text)
    except InvalidOperation:
        return None
    if rate > 1:
        rate = rate / Decimal("100")
    return float(rate)


def parse_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    text = clean_text(value)
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()
