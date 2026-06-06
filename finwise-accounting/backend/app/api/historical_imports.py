from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.historical_import import HistoricalImportBatchRead
from app.services.historical_import_service import (
    HistoricalEnterpriseNotFoundError,
    HistoricalImportError,
    import_historical_books,
)


router = APIRouter(prefix="/api/enterprises/{enterprise_id}/historical-imports", tags=["historical-imports"])

LEDGER_COLUMNS = {
    "date": "日期",
    "voucher_no": "凭证字号",
    "summary": "摘要",
    "account_full_name": "科目全称",
    "account_code": "科目编码",
    "account_name": "科目名称",
    "quantity": "数量",
    "foreign_currency": "外币",
    "debit_amount": "借方金额",
    "credit_amount": "贷方金额",
    "customer_code": "客户编码",
    "customer_name": "客户",
    "supplier_code": "供应商编码",
    "supplier_name": "供应商",
    "inventory_code": "存货编码",
    "inventory_name": "存货",
    "project_code": "项目编码",
    "project_name": "项目",
    "department_code": "部门编码",
    "department_name": "部门",
    "person_code": "人员编码",
    "person_name": "人员",
}

BALANCE_COLUMNS = [
    "account_code",
    "account_name",
    "opening_debit",
    "opening_credit",
    "period_debit",
    "period_credit",
    "closing_debit",
    "closing_credit",
]


@dataclass
class ParsedHistoricalUpload:
    rows: list[dict]
    metadata: dict
    file_hash: str


@router.post("/gbt24589", response_model=HistoricalImportBatchRead, status_code=status.HTTP_201_CREATED)
def import_gbt24589_historical_books_endpoint(
    enterprise_id: UUID,
    fiscal_year: int = Form(...),
    ledger_file: UploadFile = File(...),
    balance_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    ledger_upload = read_upload_with(ledger_file, read_historical_ledger_workbook)
    balance_upload = read_upload_with(balance_file, read_historical_balance_workbook)
    return _handle_errors(
        lambda: import_historical_books(
            db,
            enterprise_id=enterprise_id,
            fiscal_year=fiscal_year,
            ledger_rows=ledger_upload.rows,
            balance_rows=balance_upload.rows,
            ledger_filename=ledger_file.filename or "",
            balance_filename=balance_file.filename or "",
            source_metadata={**ledger_upload.metadata, **balance_upload.metadata},
            file_hashes={"ledger_sha256": ledger_upload.file_hash, "balance_sha256": balance_upload.file_hash},
        )
    )


def read_upload_with(file: UploadFile, parser: Callable[[Path], ParsedHistoricalUpload]) -> ParsedHistoricalUpload:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .xlsx and .xls files are supported.")
    content = file.file.read()
    with NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(content)
        tmp.flush()
        try:
            parsed = parser(Path(tmp.name))
            parsed.file_hash = sha256(content).hexdigest()
            return parsed
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not read import file: {exc}") from exc


def read_historical_ledger_rows(path: Path) -> list[dict]:
    return read_historical_ledger_workbook(path).rows


def read_historical_ledger_workbook(path: Path) -> ParsedHistoricalUpload:
    frame = _read_detected_frame(path, required_headers={"日期", "凭证字号", "科目编码", "借方金额", "贷方金额"})
    rows = []
    for raw in frame.to_dict(orient="records"):
        if _is_footer_or_blank(raw, code_key="科目编码"):
            continue
        rows.append({canonical: _stringify_cell(raw.get(source)) for canonical, source in LEDGER_COLUMNS.items()})
    return ParsedHistoricalUpload(rows=rows, metadata=_ledger_metadata(path), file_hash="")


def read_historical_balance_rows(path: Path) -> list[dict]:
    return read_historical_balance_workbook(path).rows


def read_historical_balance_workbook(path: Path) -> ParsedHistoricalUpload:
    workbook = pd.ExcelFile(path)
    candidates = []
    for sheet_name in workbook.sheet_names:
        preview = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=30, dtype=object)
        for row_index in range(len(preview) - 1):
            row = {_stringify_cell(value) for value in preview.iloc[row_index].tolist()}
            next_row = {_stringify_cell(value) for value in preview.iloc[row_index + 1].tolist()}
            if {"科目编码", "科目名称", "期初余额", "本期发生额", "期末余额"}.issubset(row) and {"借方", "贷方"}.issubset(next_row):
                candidates.append((sheet_name, row_index + 2))
    if not candidates:
        raise ValueError("Could not detect balance table header.")

    sheet_name, data_start = candidates[0]
    frame = pd.read_excel(path, sheet_name=sheet_name, header=None, skiprows=data_start, dtype=object)
    frame = frame.iloc[:, :8]
    frame.columns = BALANCE_COLUMNS
    rows = []
    for raw in frame.to_dict(orient="records"):
        if _is_footer_or_blank(raw, code_key="account_code"):
            continue
        rows.append({column: _stringify_cell(raw.get(column)) for column in BALANCE_COLUMNS})
    return ParsedHistoricalUpload(rows=rows, metadata=_balance_metadata(path), file_hash="")


def _read_detected_frame(path: Path, *, required_headers: set[str]) -> pd.DataFrame:
    workbook = pd.ExcelFile(path)
    candidates = []
    for sheet_name in workbook.sheet_names:
        preview = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=30, dtype=object)
        for row_index in range(len(preview)):
            headers = {_stringify_cell(value) for value in preview.iloc[row_index].tolist()}
            if required_headers.issubset(headers):
                candidates.append((sheet_name, row_index))
    if not candidates:
        raise ValueError("Could not detect historical ledger table header.")
    sheet_name, header_index = candidates[0]
    frame = pd.read_excel(path, sheet_name=sheet_name, header=header_index, dtype=object)
    return frame.dropna(how="all")


def _is_footer_or_blank(row: dict, *, code_key: str) -> bool:
    code = _stringify_cell(row.get(code_key))
    if not code:
        return True
    values = {_stringify_cell(value) for value in row.values()}
    return bool({"合计", "资产小计", "负债小计", "权益小计", "成本小计", "损益小计"} & values)


def _stringify_cell(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _ledger_metadata(path: Path) -> dict:
    workbook = pd.ExcelFile(path)
    preview = pd.read_excel(path, sheet_name=workbook.sheet_names[0], header=None, dtype=object)
    values = [_stringify_cell(value) for value in preview.to_numpy().flatten()]
    return {
        "ledger_period_text": _first_value_containing(values, "年"),
        "ledger_company_name": _company_name(values),
    }


def _balance_metadata(path: Path) -> dict:
    workbook = pd.ExcelFile(path)
    preview = pd.read_excel(path, sheet_name=workbook.sheet_names[0], header=None, nrows=10, dtype=object)
    values = [_stringify_cell(value) for value in preview.to_numpy().flatten()]
    return {
        "balance_period_text": _first_value_containing(values, "年"),
        "balance_company_name": _company_name(values),
    }


def _company_name(values: list[str]) -> str:
    for value in values:
        if "编制单位" in value:
            return value.replace("编制单位：", "").replace("编制单位:", "").strip()
    return ""


def _first_value_containing(values: list[str], token: str) -> str:
    return next((value for value in values if token in value), "")


def _handle_errors(action: Callable[[], object]):
    try:
        return action()
    except HTTPException:
        raise
    except HistoricalEnterpriseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HistoricalImportError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
