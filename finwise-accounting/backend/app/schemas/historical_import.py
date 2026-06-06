from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class HistoricalImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    organization_id: UUID
    enterprise_id: UUID
    fiscal_year: int
    source_standard: str
    ledger_filename: str
    balance_filename: str
    status: str
    created_ledger_rows: int
    created_balance_rows: int
    replaced_ledger_rows: int
    replaced_balance_rows: int
    source_metadata: dict[str, Any]
    file_hashes: dict[str, Any]
    validation_summary: dict[str, Any]
    created_at: datetime
