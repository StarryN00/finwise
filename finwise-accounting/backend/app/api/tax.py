from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.tax import TaxFilingDraftRead, TaxFilingDraftUpdate
from app.services.statement_service import MonthlyPackageNotFoundError
from app.services.tax_service import (
    TaxDraftNotFoundError,
    export_tax_filing_draft,
    generate_tax_filing_draft,
    get_tax_filing_draft,
    render_tax_filing_draft_html,
    update_tax_filing_draft,
)


router = APIRouter(tags=["tax"])


@router.post("/api/monthly-packages/{package_id}/tax/vat-draft", response_model=TaxFilingDraftRead)
def generate_tax_draft_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return generate_tax_filing_draft(db, monthly_work_package_id=package_id)
    except MonthlyPackageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/tax-drafts/{draft_id}", response_model=TaxFilingDraftRead)
def get_tax_draft_endpoint(draft_id: UUID, db: Session = Depends(get_db)):
    try:
        return get_tax_filing_draft(db, draft_id=draft_id)
    except TaxDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/api/tax-drafts/{draft_id}", response_model=TaxFilingDraftRead)
def update_tax_draft_endpoint(draft_id: UUID, payload: TaxFilingDraftUpdate, db: Session = Depends(get_db)):
    try:
        return update_tax_filing_draft(db, draft_id=draft_id, **payload.model_dump())
    except TaxDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/tax-drafts/{draft_id}/export")
def export_tax_draft_endpoint(draft_id: UUID, db: Session = Depends(get_db)):
    try:
        export_path = export_tax_filing_draft(db, draft_id=draft_id)
    except TaxDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FileResponse(
        export_path,
        filename=export_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/api/tax-drafts/{draft_id}/html", response_class=HTMLResponse)
def tax_draft_html_endpoint(draft_id: UUID, db: Session = Depends(get_db)):
    try:
        return HTMLResponse(render_tax_filing_draft_html(db, draft_id=draft_id))
    except TaxDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
