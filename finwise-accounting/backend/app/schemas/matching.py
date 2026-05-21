from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MatchRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    organization_id: UUID
    monthly_work_package_id: UUID
    bank_transaction_id: Optional[UUID]
    invoice_id: Optional[UUID]
    match_group_id: Optional[str]
    match_method: str
    confidence: int
    explanation: str
    confirmation_status: str
    created_at: datetime


class AccountingLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    organization_id: UUID
    monthly_work_package_id: UUID
    source_type: str
    source_id: str
    business_type: str
    direction: str
    amount: Decimal
    tax_amount: Decimal
    include_category: str
    confirmation_status: str
    created_at: datetime


class MatchingRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    organization_id: UUID
    enterprise_id: Optional[UUID]
    scope: str
    summary_keywords: list[str]
    counterparty_pattern: Optional[str]
    min_amount: Optional[Decimal]
    max_amount: Optional[Decimal]
    invoice_direction: Optional[str]
    suggested_business_type: str
    source: str
    created_at: datetime
