from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MonthlyPackageCreate(BaseModel):
    period_year: int = Field(ge=2020, le=2100)
    period_month: int = Field(ge=1, le=12)


class MonthlyPackageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    organization_id: UUID
    enterprise_id: UUID
    period_year: int
    period_month: int
    data_status: str
    matching_status: str
    filing_status: str
    report_status: str
    pending_confirmation_count: int
    completion_percent: int
    created_at: datetime
