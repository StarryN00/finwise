from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    organization_id: UUID
    monthly_work_package_id: UUID
    file_type: str
    original_filename: str
    stored_path: str
    parse_status: str
    field_mapping: dict[str, Any]
    error_rows: list[dict[str, Any]]
    import_summary: dict[str, Any]
    created_at: datetime


class ImportRowError(BaseModel):
    row: int
    error: str
    raw: dict[str, Any]


class ImportBatchError(BaseModel):
    error: str


class ImportResult(BaseModel):
    created: int
    errors: list[ImportRowError]
    batch_errors: list[ImportBatchError] = Field(default_factory=list)
