from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.statement import MonthlyStatementRead
from app.services.statement_service import MonthlyPackageNotFoundError, generate_monthly_statement


router = APIRouter(tags=["statements"])


@router.post("/api/monthly-packages/{package_id}/statements/generate", response_model=MonthlyStatementRead)
def generate_statement_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return generate_monthly_statement(db, monthly_work_package_id=package_id)
    except MonthlyPackageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
