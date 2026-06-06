from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TechnologyTagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    enterprise_id: UUID
    profile_id: UUID
    category: str
    name: str
    status: str
    value: str | None = None
    confidence: int
    source_provider: str
    source_url: str | None = None
    evidence_text: str
    evidence_file_path: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TechnologyProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    enterprise_id: UUID
    overall_status: str
    primary_provider: str | None = None
    last_scanned_at: datetime | None = None
    last_confirmed_at: datetime | None = None
    next_rescan_at: datetime | None = None
    summary: str
    raw_snapshot: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    tags: list[TechnologyTagRead] = Field(default_factory=list)


class TechnologyTagInput(BaseModel):
    category: str
    name: str
    status: str = "UNKNOWN"
    value: str | None = None
    confidence: int = Field(default=0, ge=0, le=100)
    source_url: str | None = None
    evidence_text: str = ""
    evidence_file_path: str | None = None


class TechnologyScanResultInput(BaseModel):
    provider: str
    source_url: str | None = None
    qichacha_innovation_text: str | None = None
    summary: str = ""
    raw_snapshot: dict[str, Any] = Field(default_factory=dict)
    tags: list[TechnologyTagInput] = Field(default_factory=list)


class TechnologyScanJobCreate(BaseModel):
    provider: str = "QICHACHA"
    scope_type: str = "UNSCANNED"
    enterprise_ids: list[UUID] = Field(default_factory=list)


class TechnologyScanItemFailureInput(BaseModel):
    failure_reason: str
    error_summary: str = ""
    source_url: str | None = None
    raw_snapshot: dict[str, Any] = Field(default_factory=dict)


class TechnologyScanItemCompleteInput(BaseModel):
    source_url: str | None = None
    qichacha_innovation_text: str | None = None
    summary: str = ""
    raw_snapshot: dict[str, Any] = Field(default_factory=dict)
    tags: list[TechnologyTagInput] = Field(default_factory=list)


class TechnologyScanJobPauseInput(BaseModel):
    failure_reason: str = "UNKNOWN_ERROR"
    error_summary: str = ""


class TechnologyScanJobItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    enterprise_id: UUID
    enterprise_name: str
    unified_social_credit_code: str
    status: str
    failure_reason: str
    source_url: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    raw_snapshot: dict[str, Any]
    error_summary: str
    created_at: datetime
    updated_at: datetime


class TechnologyScanJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: str
    scope_type: str
    status: str
    target_enterprise_count: int
    completed_enterprise_count: int
    failed_enterprise_count: int
    review_required_count: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_by: str
    error_summary: str
    created_at: datetime
    updated_at: datetime
    items: list[TechnologyScanJobItemRead] = Field(default_factory=list)


class TechnologyScanJobListRead(BaseModel):
    jobs: list[TechnologyScanJobRead] = Field(default_factory=list)
