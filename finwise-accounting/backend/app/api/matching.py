from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.matching import AccountingLineConfirmRequest
from app.services.matching_service import (
    MatchingDomainError,
    MatchingValidationError,
    MonthlyPackageNotFoundError,
    confirm_accounting_line,
    confirm_match,
    run_matching,
)


router = APIRouter(tags=["matching"])


@router.post("/api/monthly-packages/{package_id}/matching/run")
def run_matching_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return run_matching(db, monthly_work_package_id=package_id)
    except MonthlyPackageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/matches/{match_id}/confirm")
def confirm_match_endpoint(match_id: UUID, db: Session = Depends(get_db)):
    try:
        result = confirm_match(db, match_id=match_id)
    except MatchingDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match record not found.") from exc
    return result


@router.post("/api/accounting-lines/{line_id}/confirm")
def confirm_accounting_line_endpoint(
    line_id: UUID,
    payload: Optional[AccountingLineConfirmRequest] = Body(default=None),
    db: Session = Depends(get_db),
):
    try:
        result = confirm_accounting_line(
            db,
            line_id=line_id,
            save_as_rule=payload.save_as_rule if payload is not None else False,
        )
    except MatchingValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MatchingDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Accounting line not found.") from exc
    return result
