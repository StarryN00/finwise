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
        if suffix == ".csv":
            frame = pd.read_csv(tmp.name)
        else:
            frame = pd.read_excel(tmp.name)
    return frame.fillna("").to_dict(orient="records")


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
    except MonthlyPackageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (pd.errors.EmptyDataError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
