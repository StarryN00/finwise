from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.report import ReportRead
from app.services.report_service import MonthlyPackageNotFoundError, generate_health_report


router = APIRouter(tags=["reports"])


@router.post("/api/monthly-packages/{package_id}/reports/health", response_model=ReportRead)
def generate_health_report_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return generate_health_report(db, monthly_work_package_id=package_id)
    except MonthlyPackageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
