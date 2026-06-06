from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.voucher import (
    AccountSubjectRead,
    BankLedgerRowRead,
    InvoiceLedgerRowRead,
    VoucherConfirmRequest,
    VoucherGenerateResponse,
    VoucherLedgerSummaryRead,
    VoucherMergeApplyRequest,
    VoucherMergeSuggestionsResponse,
    VoucherPreprocessResponse,
    VoucherRead,
    VoucherRejectRequest,
    VoucherReopenRequest,
    VoucherRematchCandidatesResponse,
    VoucherRematchRequest,
    VoucherTreatmentAdjustmentRequest,
)
from app.services.voucher_service import (
    VoucherDomainError,
    VoucherValidationError,
    apply_voucher_merge_suggestion,
    confirm_voucher,
    ensure_enterprise_subjects,
    generate_voucher_drafts,
    get_voucher_ledger_summary,
    list_bank_ledger,
    list_invoice_ledger,
    list_voucher_rematch_candidates,
    list_enterprise_subjects,
    list_package_vouchers,
    list_voucher_merge_suggestions,
    rematch_voucher,
    reject_voucher,
    reopen_voucher,
    update_single_source_voucher_treatment,
)
from app.services.voucher_ai_preprocess_service import VoucherAiPreprocessFailedError, run_voucher_ai_preprocessing


router = APIRouter(tags=["vouchers"])


@router.post(
    "/api/enterprises/{enterprise_id}/account-subjects/initialize",
    response_model=list[AccountSubjectRead],
    status_code=status.HTTP_201_CREATED,
)
def initialize_account_subjects_endpoint(enterprise_id: UUID, db: Session = Depends(get_db)):
    try:
        return ensure_enterprise_subjects(db, enterprise_id=enterprise_id)
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/enterprises/{enterprise_id}/account-subjects", response_model=list[AccountSubjectRead])
def list_account_subjects_endpoint(enterprise_id: UUID, db: Session = Depends(get_db)):
    try:
        return list_enterprise_subjects(db, enterprise_id=enterprise_id)
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/api/monthly-packages/{package_id}/vouchers/generate",
    response_model=VoucherGenerateResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_vouchers_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return generate_voucher_drafts(db, monthly_work_package_id=package_id)
    except VoucherValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/api/monthly-packages/{package_id}/vouchers/preprocess",
    response_model=VoucherPreprocessResponse,
    status_code=status.HTTP_201_CREATED,
)
def preprocess_vouchers_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return run_voucher_ai_preprocessing(db, monthly_work_package_id=package_id)
    except VoucherAiPreprocessFailedError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except VoucherValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/monthly-packages/{package_id}/vouchers", response_model=list[VoucherRead])
def list_vouchers_endpoint(
    package_id: UUID,
    voucher_status: str | None = Query(default=None, alias="status"),
    keyword: str | None = None,
    db: Session = Depends(get_db),
):
    try:
        return list_package_vouchers(
            db,
            monthly_work_package_id=package_id,
            status=voucher_status,
            keyword=keyword,
        )
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/monthly-packages/{package_id}/bank-ledger", response_model=list[BankLedgerRowRead])
def list_bank_ledger_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return list_bank_ledger(db, monthly_work_package_id=package_id)
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/monthly-packages/{package_id}/invoice-ledger", response_model=list[InvoiceLedgerRowRead])
def list_invoice_ledger_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return list_invoice_ledger(db, monthly_work_package_id=package_id)
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/monthly-packages/{package_id}/voucher-ledger-summary", response_model=VoucherLedgerSummaryRead)
def voucher_ledger_summary_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return get_voucher_ledger_summary(db, monthly_work_package_id=package_id)
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/api/monthly-packages/{package_id}/vouchers/merge-suggestions",
    response_model=VoucherMergeSuggestionsResponse,
)
def voucher_merge_suggestions_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return list_voucher_merge_suggestions(db, monthly_work_package_id=package_id)
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/monthly-packages/{package_id}/vouchers/merge-suggestions/apply", response_model=VoucherRead)
def apply_voucher_merge_suggestion_endpoint(
    package_id: UUID,
    payload: VoucherMergeApplyRequest,
    db: Session = Depends(get_db),
):
    try:
        return apply_voucher_merge_suggestion(
            db,
            monthly_work_package_id=package_id,
            source_voucher_ids=payload.source_voucher_ids,
            applied_by=payload.applied_by,
        )
    except VoucherValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/vouchers/{voucher_id}/confirm", response_model=VoucherRead)
def confirm_voucher_endpoint(voucher_id: UUID, payload: VoucherConfirmRequest, db: Session = Depends(get_db)):
    try:
        return confirm_voucher(db, voucher_id=voucher_id, confirmed_by=payload.confirmed_by)
    except VoucherValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/vouchers/{voucher_id}/reject", response_model=VoucherRead)
def reject_voucher_endpoint(voucher_id: UUID, payload: VoucherRejectRequest, db: Session = Depends(get_db)):
    try:
        return reject_voucher(db, voucher_id=voucher_id, rejected_by=payload.rejected_by, reason=payload.reason)
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/vouchers/{voucher_id}/reopen", response_model=VoucherRead)
def reopen_voucher_endpoint(voucher_id: UUID, payload: VoucherReopenRequest, db: Session = Depends(get_db)):
    try:
        return reopen_voucher(db, voucher_id=voucher_id, reopened_by=payload.reopened_by, reason=payload.reason)
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/vouchers/{voucher_id}/rematch-candidates", response_model=VoucherRematchCandidatesResponse)
def rematch_candidates_endpoint(voucher_id: UUID, db: Session = Depends(get_db)):
    try:
        return list_voucher_rematch_candidates(db, voucher_id=voucher_id)
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/vouchers/{voucher_id}/rematch", response_model=VoucherRead)
def rematch_voucher_endpoint(voucher_id: UUID, payload: VoucherRematchRequest, db: Session = Depends(get_db)):
    try:
        return rematch_voucher(
            db,
            voucher_id=voucher_id,
            bank_transaction_id=payload.bank_transaction_id,
            invoice_id=payload.invoice_id,
            bank_transaction_ids=payload.bank_transaction_ids,
            invoice_ids=payload.invoice_ids,
        )
    except VoucherValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/vouchers/{voucher_id}/treatment-adjustment", response_model=VoucherRead)
def treatment_adjustment_endpoint(
    voucher_id: UUID,
    payload: VoucherTreatmentAdjustmentRequest,
    db: Session = Depends(get_db),
):
    try:
        return update_single_source_voucher_treatment(
            db,
            voucher_id=voucher_id,
            treatment_type=payload.treatment_type,
            summary=payload.summary,
            debit_account_code=payload.debit_account_code,
            credit_account_code=payload.credit_account_code,
            note=payload.note,
        )
    except VoucherValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
