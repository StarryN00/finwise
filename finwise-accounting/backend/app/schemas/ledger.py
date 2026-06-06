from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class LedgerSummaryRead(BaseModel):
    confirmed_voucher_count: int
    pending_voucher_count: int
    entry_count: int
    is_final: bool


class JournalLedgerRowRead(BaseModel):
    voucher_id: str
    voucher_entry_id: str
    voucher_date: date
    voucher_number: str
    summary: str
    account_code: str
    account_name: str
    direction: str
    direction_label: str
    debit_amount: Decimal
    credit_amount: Decimal
    source_type: str


class GeneralLedgerRowRead(BaseModel):
    account_code: str
    account_name: str
    account_category: str
    balance_direction: str
    balance_direction_label: str
    opening_debit: Decimal
    opening_credit: Decimal
    period_debit: Decimal
    period_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal
    row_type: str = "ACCOUNT"
    parent_account_code: Optional[str] = None
    auxiliary_type: Optional[str] = None
    auxiliary_code: Optional[str] = None
    auxiliary_name: Optional[str] = None
    display_code: Optional[str] = None
    display_name: Optional[str] = None
    level: int = 0
    is_expandable: bool = False


class DetailLedgerRowRead(BaseModel):
    voucher_id: str
    voucher_entry_id: str
    voucher_date: date
    voucher_number: str
    summary: str
    counter_accounts: str
    counter_account_display: Optional[str] = None
    counter_account_name: Optional[str] = None
    counter_auxiliary_type: Optional[str] = None
    counter_auxiliary_name: Optional[str] = None
    debit_amount: Decimal
    credit_amount: Decimal
    balance_direction: str
    balance_direction_label: str
    balance: Decimal


class TrialBalanceRead(BaseModel):
    rows: list[GeneralLedgerRowRead]
    opening_debit_total: Decimal
    opening_credit_total: Decimal
    period_debit_total: Decimal
    period_credit_total: Decimal
    closing_debit_total: Decimal
    closing_credit_total: Decimal
    is_balanced: bool
    difference: Decimal


class AccountOptionRead(BaseModel):
    account_code: str
    account_name: str
    account_category: str


class LedgerPayloadRead(BaseModel):
    summary: LedgerSummaryRead
    rows: list[JournalLedgerRowRead | GeneralLedgerRowRead | DetailLedgerRowRead]
    trial_balance: Optional[TrialBalanceRead] = None
