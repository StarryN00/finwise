from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TaxFilingDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    organization_id: UUID
    monthly_work_package_id: UUID
    data: dict[str, Any]
    status: str
    export_path: Optional[str]
    created_at: datetime


class TaxFilingDraftUpdate(BaseModel):
    output_amount: Decimal
    output_tax: Decimal
    input_amount: Decimal
    input_tax: Decimal
