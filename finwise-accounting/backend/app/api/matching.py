from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.matching import AccountingLineConfirmRequest, MatchingRuleCreate, MatchingRuleRead, UnmatchedConfirmRequest
from app.services.ai_matching_service import AiMatchingUnavailableError, run_ai_matching
from app.services.matching_service import (
    MatchingDomainError,
    MatchingValidationError,
    MonthlyPackageNotFoundError,
    confirm_accounting_line,
    confirm_match,
    confirm_unmatched_source,
    create_enterprise_matching_rule,
    delete_matching_rule,
    list_matching_rules,
    run_matching,
)


router = APIRouter(tags=["matching"])


@router.post("/api/monthly-packages/{package_id}/matching/run")
def run_matching_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return run_matching(db, monthly_work_package_id=package_id)
    except MonthlyPackageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/monthly-packages/{package_id}/matching/ai-run")
def run_ai_matching_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return run_ai_matching(db, monthly_work_package_id=package_id)
    except AiMatchingUnavailableError as exc:
        return {
            "aiStatus": "UNAVAILABLE",
            "message": str(exc),
            "created_matches": 0,
            "uncertain_matches": 0,
            "candidate_transactions": 0,
            "candidate_invoices": 0,
        }
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


@router.post("/api/monthly-packages/{package_id}/confirm-unmatched")
def confirm_unmatched_endpoint(
    package_id: UUID,
    payload: UnmatchedConfirmRequest,
    db: Session = Depends(get_db),
):
    try:
        return confirm_unmatched_source(
            db,
            monthly_work_package_id=package_id,
            source_type=payload.source_type,
            source_id=payload.source_id,
            business_type=payload.business_type,
            save_as_rule=payload.save_as_rule,
        )
    except MatchingValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MatchingDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/rules", response_model=list[MatchingRuleRead])
def list_rules_endpoint(enterprise_id: Optional[UUID] = None, db: Session = Depends(get_db)):
    return list_matching_rules(db, enterprise_id=enterprise_id)


@router.post("/api/rules", response_model=MatchingRuleRead, status_code=status.HTTP_201_CREATED)
def create_rule_endpoint(payload: MatchingRuleCreate, db: Session = Depends(get_db)):
    return create_enterprise_matching_rule(
        db,
        enterprise_id=payload.enterprise_id,
        summary_keywords=payload.summary_keywords,
        suggested_business_type=payload.suggested_business_type,
        counterparty_pattern=payload.counterparty_pattern,
        min_amount=payload.min_amount,
        max_amount=payload.max_amount,
        invoice_direction=payload.invoice_direction,
    )


@router.delete("/api/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule_endpoint(rule_id: UUID, db: Session = Depends(get_db)):
    try:
        delete_matching_rule(db, rule_id=rule_id)
    except MatchingDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
