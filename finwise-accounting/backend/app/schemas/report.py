from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    organization_id: UUID
    monthly_work_package_id: UUID
    report_type: str
    data_version: dict[str, Any]
    html_path: Optional[str]
    export_path: Optional[str]
    status: str
    created_at: datetime
