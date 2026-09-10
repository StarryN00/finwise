from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    legal_entity_id: str = Field(min_length=1)
    ledger_id: str = Field(min_length=1)
    accounting_period_id: str = Field(min_length=1)
    baseline_id: str = Field(min_length=1)


class SourceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: Optional[int] = Field(default=None, ge=1)
    row: Optional[int] = Field(default=None, ge=1)
    field: Optional[str] = None
    region: Optional[str] = None

    @field_validator("field", "region")
    @classmethod
    def non_empty_if_present(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("定位字段不能为空")
        return value


class AgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "PROPOSED"
    summary: str
    confidence: float = Field(ge=0, le=1)
    items: List[Dict[str, Any]] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    risk_level: str
    next_action: str

    @field_validator("status")
    @classmethod
    def proposed_only(cls, value: str) -> str:
        if value != "PROPOSED":
            raise ValueError("Agent 输出必须保持 PROPOSED 候选状态")
        return value


class CommandRequest(BaseModel):
    action: str
    target_id: str
    target_version: int = Field(ge=1)
    scope: Scope
    idempotency_key: str = Field(min_length=8)
    payload: Dict[str, Any] = Field(default_factory=dict)


class ArtifactInput(BaseModel):
    scope: Scope
    filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    source_channel: str = "UPLOAD"
    observed_period: Optional[str] = None
    mime_type: str = "application/octet-stream"
    source_purpose: Optional[Literal["opening_balance", "prior_close", "business", "historical_reference"]] = None


class FactInput(BaseModel):
    scope: Scope
    source_artifact_id: str
    source_anchor: SourceAnchor
    record_type: str
    original_value: dict[str, Any]
    normalized_value: dict[str, Any]
    parser_version: str
    extraction_confidence: float = Field(ge=0, le=1)
    period_check: str = "PASS"


class ScopeQuery(BaseModel):
    scope: Scope


class QueryRequest(BaseModel):
    scope: Scope
    question: str = Field(min_length=2)


class DemoRequest(BaseModel):
    scope: Scope
    variant: str = "normal"
