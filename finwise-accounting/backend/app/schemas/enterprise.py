from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EnterpriseCreate(BaseModel):
    organization_id: UUID
    name: str
    unified_social_credit_code: str
    taxpayer_type: str
    industry: str
    province: str = "江苏省"
    city: str = "苏州市"


class InitialSnapshotCreate(BaseModel):
    organization_id: UUID
    enterprise_id: UUID
    balance_sheet_data: dict[str, Any] = Field(default_factory=dict)
    income_statement_data: dict[str, Any] = Field(default_factory=dict)
    validation_result: dict[str, Any] = Field(default_factory=dict)


class EnterpriseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    unified_social_credit_code: str
    taxpayer_type: str
    industry: str
    province: str
    city: str
    status: str
    created_at: datetime
    updated_at: datetime
