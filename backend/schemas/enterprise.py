"""
Enterprise schemas - Pydantic models for API requests/responses
"""
from datetime import datetime, date
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field


class TaxpayerType(str, Enum):
    GENERAL = "GENERAL"
    SMALL = "SMALL"


class EnterpriseSource(str, Enum):
    DIRECT = "DIRECT"
    LIU = "LIU"
    PING = "PING"


class EnterpriseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class EnterpriseBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    tax_number: Optional[str] = Field(None, max_length=50)
    taxpayer_type: TaxpayerType = TaxpayerType.SMALL
    industry: Optional[str] = Field(None, max_length=100)
    registered_capital_range: Optional[str] = Field(None, max_length=50)
    founded_year: Optional[int] = Field(None, ge=1900, le=2100)
    province: Optional[str] = Field(None, max_length=50)
    city: Optional[str] = Field(None, max_length=50)
    source: EnterpriseSource = EnterpriseSource.DIRECT


class EnterpriseCreate(EnterpriseBase):
    assigned_operator_id: Optional[str] = None


class EnterpriseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    tax_number: Optional[str] = Field(None, max_length=50)
    taxpayer_type: Optional[TaxpayerType] = None
    industry: Optional[str] = Field(None, max_length=100)
    registered_capital_range: Optional[str] = Field(None, max_length=50)
    founded_year: Optional[int] = Field(None, ge=1900, le=2100)
    province: Optional[str] = Field(None, max_length=50)
    city: Optional[str] = Field(None, max_length=50)
    source: Optional[EnterpriseSource] = None
    status: Optional[EnterpriseStatus] = None


class EnterpriseResponse(EnterpriseBase):
    id: str
    channel_id: str
    assigned_operator_id: Optional[str] = None
    status: EnterpriseStatus = EnterpriseStatus.ACTIVE
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EnterpriseListItem(BaseModel):
    id: str
    name: str
    industry: Optional[str] = None
    financing_score: Optional[int] = None
    last_analysis_date: Optional[date] = None
    status: EnterpriseStatus
    source: EnterpriseSource


class EnterpriseSummary(BaseModel):
    total_count: int
    active_count: int
    high_potential_count: int
    pending_analysis_count: int


class EnterpriseListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[EnterpriseListItem]
