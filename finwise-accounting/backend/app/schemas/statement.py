from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MonthlyStatementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    organization_id: UUID
    monthly_work_package_id: UUID
    estimated_balance_sheet: dict[str, Any]
    estimated_income_statement: dict[str, Any]
    formal_balance_sheet: dict[str, Any]
    formal_income_statement: dict[str, Any]
    difference_summary: dict[str, Any]
    created_at: datetime
