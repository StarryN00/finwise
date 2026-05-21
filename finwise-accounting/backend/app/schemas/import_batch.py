from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    monthly_work_package_id: UUID
    file_type: str
    original_filename: str
    stored_path: str
    parse_status: str
    field_mapping: dict
    error_rows: list
    import_summary: dict
    created_at: datetime
