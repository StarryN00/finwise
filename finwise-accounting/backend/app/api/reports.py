from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.org_context import get_current_organization_id
from app.models import Report
from app.schemas.report import ReportRead
from app.services.report_service import MonthlyPackageNotFoundError, generate_health_report


router = APIRouter(tags=["reports"])


@router.post("/api/monthly-packages/{package_id}/reports/health", response_model=ReportRead)
def generate_health_report_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return generate_health_report(db, monthly_work_package_id=package_id)
    except MonthlyPackageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/reports/{report_id}/html", response_class=HTMLResponse)
def report_html_endpoint(report_id: UUID, db: Session = Depends(get_db)):
    report = db.scalar(
        select(Report).where(
            Report.id == report_id,
            Report.organization_id == get_current_organization_id(),
        )
    )
    if report is None or not report.html_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report html not found.")
    path = Path(report.html_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report html not found.")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@router.get("/api/reports/{report_id}/pdf")
def report_pdf_endpoint(report_id: UUID, db: Session = Depends(get_db)):
    report = db.scalar(
        select(Report).where(
            Report.id == report_id,
            Report.organization_id == get_current_organization_id(),
        )
    )
    if report is None or not report.export_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report pdf not found.")
    path = Path(report.export_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report pdf not found.")
    return FileResponse(path, media_type="application/pdf", filename=path.name)
