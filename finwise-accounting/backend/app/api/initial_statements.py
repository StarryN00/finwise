from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.services.initial_statement_service import InitialStatementParseError, parse_initial_statement


router = APIRouter(prefix="/api/initial-statements", tags=["initial-statements"])


@router.post("/parse")
def parse_initial_statement_endpoint(
    statement_type: str = Form(...),
    file: UploadFile = File(...),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".xlsx", ".xls"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .xlsx and .xls files are supported.",
        )

    with NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(file.file.read())
        tmp.flush()
        try:
            return parse_initial_statement(Path(tmp.name), statement_type=statement_type)
        except InitialStatementParseError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not parse statement: {exc}") from exc
