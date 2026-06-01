from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AccountSubjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    organization_id: UUID
    enterprise_id: UUID
    code: str
    name: str
    category: str
    normal_balance: str
    parent_code: Optional[str]
    is_leaf: bool
    is_enabled: bool
    allow_voucher: bool
    is_common: bool
    created_at: datetime
    updated_at: datetime


class VoucherEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    organization_id: UUID
    voucher_id: UUID
    line_no: int
    direction: str
    account_code: str
    account_name: str
    amount: Decimal
    source_type: str
    source_id: str


class VoucherRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    organization_id: UUID
    monthly_work_package_id: UUID
    voucher_date: date
    voucher_number: Optional[str]
    summary: str
    attachment_count: int
    source_key: str
    source_data: dict
    ai_confidence: int
    ai_reason: str
    status: str
    validation_errors: list
    confirmed_by: Optional[str]
    confirmed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    entries: list[VoucherEntryRead]


class VoucherGenerateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    created_vouchers: int
    vouchers: list[VoucherRead]


class VoucherLedgerLinkRead(BaseModel):
    id: UUID
    voucher_number: str
    status: str
    status_label: str
    summary: str
    task_type: str
    ai_confidence: int


class VoucherPreprocessAuditRead(BaseModel):
    used_kimi: bool
    ai_status: str
    model: str
    input_bank_count: int
    input_invoice_count: int
    generated_task_counts: dict
    created_vouchers: int
    duration_ms: int
    error_summary: str = ""


class VoucherPreprocessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ai_status: str
    used_kimi: bool
    message: str
    created_vouchers: int
    vouchers: list[VoucherRead]
    audit: VoucherPreprocessAuditRead


class BankLedgerRowRead(BaseModel):
    id: UUID
    source_type: str = "BANK"
    transaction_date: date
    summary: str
    direction: str
    direction_label: str
    counterparty_name: str
    debit_amount: Decimal
    credit_amount: Decimal
    transaction_amount: Decimal
    balance: Optional[Decimal]
    matching_status: str
    matching_status_label: str
    voucher_status: str
    voucher_status_label: str
    linked_invoice_count: int = 0
    linked_voucher_count: int = 0
    linked_voucher_numbers: list[str] = []
    linked_vouchers: list[VoucherLedgerLinkRead] = []


class InvoiceLedgerRowRead(BaseModel):
    id: UUID
    source_type: str = "INVOICE"
    invoice_direction: str
    invoice_direction_label: str
    invoice_number: str
    invoice_date: date
    counterparty_name: str
    counterparty_role: str
    amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    matching_status: str
    matching_status_label: str
    voucher_status: str
    voucher_status_label: str
    linked_bank_count: int = 0
    linked_voucher_count: int = 0
    linked_voucher_numbers: list[str] = []
    linked_vouchers: list[VoucherLedgerLinkRead] = []


class VoucherLedgerSummaryRead(BaseModel):
    bank_total_count: int
    bank_processed_count: int
    bank_pending_count: int
    invoice_total_count: int
    invoice_processed_count: int
    invoice_pending_count: int
    voucher_total_count: int
    pending_task_count: int
    difference_total_amount: Decimal
    single_source_total_amount: Decimal


class VoucherConfirmRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    confirmed_by: str = "operator"


class VoucherRejectRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rejected_by: str = "operator"
    reason: str = ""


class VoucherReopenRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reopened_by: str = "operator"
    reason: str = ""


class VoucherRematchCandidateRead(BaseModel):
    id: UUID
    source_type: str
    date: Optional[date]
    amount: Decimal
    counterparty: str
    counterparty_role: str = ""
    direction_label: str = ""
    description: str
    score: int
    reason: str
    detail: dict = {}
    is_current: bool = False
    is_used: bool = False
    is_selectable: bool = True
    used_by_status: Optional[str] = None
    disabled_reason: str = ""


class VoucherRematchCandidatesResponse(BaseModel):
    current_bank_transaction_id: Optional[UUID]
    current_invoice_id: Optional[UUID]
    bank_candidates: list[VoucherRematchCandidateRead]
    invoice_candidates: list[VoucherRematchCandidateRead]


class VoucherRematchRequest(BaseModel):
    bank_transaction_id: Optional[UUID] = None
    invoice_id: Optional[UUID] = None
    bank_transaction_ids: list[UUID] | None = None
    invoice_ids: list[UUID] | None = None


class VoucherTreatmentAdjustmentRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    treatment_type: str
    summary: str
    debit_account_code: str
    credit_account_code: str
    note: str = ""
