from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.ledger import (
    AccountOptionRead,
    DetailLedgerRowRead,
    GeneralLedgerRowRead,
    JournalLedgerRowRead,
    LedgerSummaryRead,
    TrialBalanceRead,
)
from app.services.ledger_service import LedgerService


router = APIRouter(prefix="/api/monthly-packages/{package_id}/ledgers", tags=["ledgers"])


@router.get("/summary", response_model=LedgerSummaryRead)
def get_ledger_summary(package_id: UUID, db: Session = Depends(get_db)) -> LedgerSummaryRead:
    return LedgerService(db).get_summary(package_id)


@router.get("/accounts", response_model=list[AccountOptionRead])
def list_ledger_accounts(package_id: UUID, db: Session = Depends(get_db)) -> list[AccountOptionRead]:
    return LedgerService(db).get_account_options(package_id)


@router.get("/journal", response_model=list[JournalLedgerRowRead])
def list_journal_ledger(package_id: UUID, db: Session = Depends(get_db)) -> list[JournalLedgerRowRead]:
    return LedgerService(db).get_journal(package_id)


@router.get("/general", response_model=list[GeneralLedgerRowRead])
def list_general_ledger(package_id: UUID, db: Session = Depends(get_db)) -> list[GeneralLedgerRowRead]:
    return LedgerService(db).get_general(package_id)


@router.get("/detail", response_model=list[DetailLedgerRowRead])
def list_detail_ledger(
    package_id: UUID,
    account_code: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> list[DetailLedgerRowRead]:
    return LedgerService(db).get_detail(package_id, account_code)


@router.get("/trial-balance", response_model=TrialBalanceRead)
def get_trial_balance(package_id: UUID, db: Session = Depends(get_db)) -> TrialBalanceRead:
    return LedgerService(db).get_trial_balance(package_id)
