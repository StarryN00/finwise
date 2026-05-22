from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import AccountingLine, AuditLog, MatchRecord
from app.services.matching_service import MonthlyPackageNotFoundError, run_matching


router = APIRouter(tags=["matching"])


@router.post("/api/monthly-packages/{package_id}/matching/run")
def run_matching_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return run_matching(db, monthly_work_package_id=package_id)
    except MonthlyPackageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/matches/{match_id}/confirm")
def confirm_match_endpoint(match_id: UUID, db: Session = Depends(get_db)):
    match = db.get(MatchRecord, match_id)
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match record not found.")

    before = {"confirmation_status": match.confirmation_status}
    match.confirmation_status = "CONFIRMED"
    _add_audit_log(
        db,
        organization_id=match.organization_id,
        monthly_work_package_id=match.monthly_work_package_id,
        action="CONFIRM_MATCH",
        before_data=before,
        after_data={"confirmation_status": match.confirmation_status},
    )
    db.commit()
    db.refresh(match)
    return {"id": match.id, "confirmation_status": match.confirmation_status}


@router.post("/api/accounting-lines/{line_id}/confirm")
def confirm_accounting_line_endpoint(line_id: UUID, db: Session = Depends(get_db)):
    line = db.get(AccountingLine, line_id)
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Accounting line not found.")

    before = {"confirmation_status": line.confirmation_status}
    line.confirmation_status = "CONFIRMED"
    _add_audit_log(
        db,
        organization_id=line.organization_id,
        monthly_work_package_id=line.monthly_work_package_id,
        action="CONFIRM_ACCOUNTING_LINE",
        before_data=before,
        after_data={"confirmation_status": line.confirmation_status},
    )
    db.commit()
    db.refresh(line)
    return {"id": line.id, "confirmation_status": line.confirmation_status}


def _add_audit_log(
    db: Session,
    *,
    organization_id: UUID,
    monthly_work_package_id: UUID,
    action: str,
    before_data: dict,
    after_data: dict,
) -> None:
    db.add(
        AuditLog(
            organization_id=organization_id,
            monthly_work_package_id=monthly_work_package_id,
            actor="system",
            action=action,
            before_data=before_data,
            after_data=after_data,
        )
    )
