from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MonthlyStatementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    monthly_work_package_id: UUID
    estimated_balance_sheet: dict
    estimated_income_statement: dict
    formal_balance_sheet: dict
    formal_income_statement: dict
    difference_summary: dict
    created_at: datetime
