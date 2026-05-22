from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.import_batch import ImportResult
from app.services.import_service import (
    BANK_COLUMNS,
    INVOICE_COLUMNS,
    ImportValidationError,
    MonthlyPackageNotFoundError,
    import_bank_rows,
    import_invoice_rows,
)


router = APIRouter(prefix="/api/monthly-packages/{package_id}/imports", tags=["imports"])


def read_upload_rows(file: UploadFile) -> list[dict]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .csv, .xlsx, and .xls files are supported.",
        )

    with NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(file.file.read())
        tmp.flush()
        try:
            frame = _read_import_frame(tmp.name, suffix)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not read import file: {exc}",
            ) from exc
    return frame.to_dict(orient="records")


def _read_import_frame(path: str, suffix: str) -> pd.DataFrame:
    if suffix == ".csv":
        last_error: Exception | None = None
        for encoding in ("utf-8", "gb18030", "gbk"):
            try:
                return pd.read_csv(path, encoding=encoding)
            except UnicodeDecodeError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
    frame = _read_excel_preferred_sheet(path)
    if _has_required_import_columns(frame):
        return _drop_summary_rows(frame)

    detected = _detect_excel_import_frame(path)
    if detected is not None:
        return detected
    return frame


def _read_excel_preferred_sheet(path: str, **kwargs) -> pd.DataFrame:
    workbook = pd.ExcelFile(path)
    sheet_name = "发票基础信息" if "发票基础信息" in workbook.sheet_names else workbook.sheet_names[0]
    return pd.read_excel(path, sheet_name=sheet_name, **kwargs)


def _detect_excel_import_frame(path: str) -> pd.DataFrame | None:
    workbook = pd.ExcelFile(path)
    candidates = []
    for sheet_name in workbook.sheet_names:
        preview = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=30)
        for row_index in range(len(preview)):
            headers = {str(value).strip() for value in preview.iloc[row_index].dropna().tolist()}
            score = _import_header_score(headers)
            if score >= 6:
                candidates.append((score, sheet_name, row_index))

    if not candidates:
        return None

    _score, sheet_name, row_index = max(candidates, key=lambda item: item[0])
    detected = pd.read_excel(path, sheet_name=sheet_name, header=row_index)
    return _drop_summary_rows(detected)


def _has_required_import_columns(frame: pd.DataFrame) -> bool:
    columns = {str(column).strip() for column in frame.columns}
    return _looks_like_bank_header(columns) or _looks_like_invoice_header(columns)


def _looks_like_bank_header(columns: set[str]) -> bool:
    return _import_header_score(columns) >= 6


def _looks_like_invoice_header(columns: set[str]) -> bool:
    return _has_any(columns, INVOICE_COLUMNS["invoice_date"]) and _has_any(columns, INVOICE_COLUMNS["invoice_number"])


def _import_header_score(columns: set[str]) -> int:
    score = 0
    if _has_any(columns, BANK_COLUMNS["transaction_date"]):
        score += 3
    if _has_any(columns, BANK_COLUMNS["summary"]):
        score += 2
    if _has_any(columns, BANK_COLUMNS["debit_amount"]) and _has_any(columns, BANK_COLUMNS["credit_amount"]):
        score += 4
    elif _has_any(columns, BANK_COLUMNS["single_amount"]):
        score += 4
    if _has_any(columns, BANK_COLUMNS["balance"]):
        score += 1
    if _has_any(columns, BANK_COLUMNS["counterparty_name"]) or _has_any(columns, BANK_COLUMNS["counterparty_account"]):
        score += 1
    return score


def _has_any(columns: set[str], aliases: list[str]) -> bool:
    normalized_columns = {_normalize_header(column) for column in columns}
    for alias in aliases:
        normalized_alias = _normalize_header(alias)
        if any(normalized_alias == column or normalized_alias in column for column in normalized_columns):
            return True
    return False


def _normalize_header(value: str) -> str:
    return str(value).strip().replace("\n", "").replace(" ", "")


def _drop_summary_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if "序号" in frame.columns:
        frame = frame[frame["序号"].astype(str) != "合计行"]
    return frame.dropna(how="all")


@router.post("/bank", response_model=ImportResult)
def import_bank_endpoint(package_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db)):
    return _handle_import_errors(
        lambda: import_bank_rows(
            db,
            monthly_work_package_id=package_id,
            rows=read_upload_rows(file),
        )
    )


@router.post("/input-invoices", response_model=ImportResult)
def import_input_invoices_endpoint(package_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db)):
    return _handle_import_errors(
        lambda: import_invoice_rows(
            db,
            monthly_work_package_id=package_id,
            direction="INPUT",
            rows=read_upload_rows(file),
        )
    )


@router.post("/output-invoices", response_model=ImportResult)
def import_output_invoices_endpoint(package_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db)):
    return _handle_import_errors(
        lambda: import_invoice_rows(
            db,
            monthly_work_package_id=package_id,
            direction="OUTPUT",
            rows=read_upload_rows(file),
        )
    )


def _handle_import_errors(action: Callable[[], dict]):
    try:
        return action()
    except HTTPException:
        raise
    except MonthlyPackageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
