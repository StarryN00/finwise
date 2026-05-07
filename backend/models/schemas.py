import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Any
from pydantic import BaseModel, ConfigDict


# ============ Auth ============

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    real_name: str
    role: str
    status: str
    created_at: datetime


# ============ Enterprise ============

class EnterpriseCreate(BaseModel):
    name: str
    tax_number: str
    taxpayer_type: str = "GENERAL"
    industry: Optional[str] = None
    registered_capital_range: Optional[str] = None
    founded_year: Optional[int] = None
    province: Optional[str] = None
    city: Optional[str] = None
    source: str = "DIRECT"
    assigned_operator_id: Optional[uuid.UUID] = None


class EnterpriseUpdate(BaseModel):
    name: Optional[str] = None
    taxpayer_type: Optional[str] = None
    industry: Optional[str] = None
    registered_capital_range: Optional[str] = None
    founded_year: Optional[int] = None
    province: Optional[str] = None
    city: Optional[str] = None
    status: Optional[str] = None


class EnterpriseResponse(BaseModel):
    id: uuid.UUID
    name: str
    tax_number: str
    taxpayer_type: str
    industry: Optional[str]
    province: Optional[str]
    city: Optional[str]
    source: str
    status: str
    financing_score: Optional[int] = None
    last_analysis_date: Optional[date] = None
    created_at: datetime


class EnterpriseSummary(BaseModel):
    id: uuid.UUID
    name: str
    industry: Optional[str]
    financing_score: Optional[int]
    last_analysis_date: Optional[date]
    status: str
    source: str


class EnterpriseListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[EnterpriseSummary]


# ============ Import ============

class ImportJobResponse(BaseModel):
    id: uuid.UUID
    enterprise_id: uuid.UUID
    import_type: str
    file_name: str
    total_rows: int
    processed_rows: int
    status: str
    error_message: Optional[str]
    created_at: datetime


# ============ Bank Statement ============

class BankStatementParseRequest(BaseModel):
    enterprise_id: uuid.UUID
    file_id: uuid.UUID


class BankStatementParseResponse(BaseModel):
    job_id: uuid.UUID
    status: str


class TransactionConfirmItem(BaseModel):
    row_index: int
    transaction_date: date
    summary: str
    debit_amount: Optional[Decimal] = None
    credit_amount: Optional[Decimal] = None
    balance: Optional[Decimal] = None
    status: str  # CONFIRMED | DELETED


class BankStatementConfirmRequest(BaseModel):
    enterprise_id: uuid.UUID
    import_batch_id: uuid.UUID
    transactions: List[TransactionConfirmItem]


class ParsedTransaction(BaseModel):
    row_index: int
    transaction_date: str
    summary: str
    debit_amount: Optional[float] = None
    credit_amount: Optional[float] = None
    balance: Optional[float] = None
    confidence: float


class BankStatementPreviewResponse(BaseModel):
    job_id: uuid.UUID
    enterprise_id: uuid.UUID
    status: str
    transactions: List[ParsedTransaction]
    total_rows: int
    ai_model: str


# ============ Invoice ============

class InvoiceItem(BaseModel):
    invoice_number: str
    invoice_type: str
    issue_date: date
    amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    seller_name: str
    seller_tax_number: str
    buyer_name: str
    buyer_tax_number: str


class InvoiceImportRequest(BaseModel):
    enterprise_id: uuid.UUID
    invoices: List[InvoiceItem]


class InvoiceResponse(BaseModel):
    id: uuid.UUID
    enterprise_id: uuid.UUID
    invoice_number: str
    invoice_type: str
    issue_date: date
    amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    seller_name: str
    status: str
    matched_invoice_id: Optional[uuid.UUID] = None
    created_at: datetime


# ============ Matching ============

class MatchCandidate(BaseModel):
    transaction_index: int
    invoice_index: int
    confidence: float
    match_reason: str


class MatchRequest(BaseModel):
    enterprise_id: uuid.UUID


class MatchResponse(BaseModel):
    enterprise_id: uuid.UUID
    job_id: uuid.UUID
    status: str
    candidates: List[MatchCandidate]
    unmatched_transactions: List[int]
    unmatched_invoices: List[int]


class MatchConfirmItem(BaseModel):
    transaction_id: uuid.UUID
    invoice_id: Optional[uuid.UUID] = None  # None means unmatch


class MatchConfirmRequest(BaseModel):
    enterprise_id: uuid.UUID
    matches: List[MatchConfirmItem]


# ============ VAT ============

class VATCalculateRequest(BaseModel):
    enterprise_id: uuid.UUID
    period_year: int
    period_month: int


class VATDetailItem(BaseModel):
    item: str
    amount: Decimal


class VATCalculateResponse(BaseModel):
    filing_id: uuid.UUID
    sales_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    surcharge_amount: Decimal
    total_tax: Decimal
    details: List[VATDetailItem]


class VATFilingResponse(BaseModel):
    id: uuid.UUID
    enterprise_id: uuid.UUID
    period_year: int
    period_month: int
    sales_amount: Decimal
    tax_amount: Decimal
    surcharge_amount: Decimal
    total_tax: Decimal
    status: str
    excel_url: Optional[str]
    created_at: datetime


# ============ Health Analysis ============

class HealthAnalysisRequest(BaseModel):
    enterprise_id: uuid.UUID
    report_type: str = "FULL"


class HealthAnalysisResponse(BaseModel):
    report_id: uuid.UUID
    status: str


class HealthReportResponse(BaseModel):
    id: uuid.UUID
    enterprise_id: uuid.UUID
    report_number: str
    analysis_date: date
    overall_score: int
    overall_grade: str
    profitability_score: float
    solvency_score: float
    operation_efficiency_score: float
    growth_score: float
    cash_flow_score: float
    radar_data: dict
    key_metrics: dict
    ai_interpretation: Optional[str]
    risk_alerts: List[str]
    improvement_suggestions: List[str]
    financing_score: Optional[int]
    estimated_loan_amount: Optional[Decimal]
    matched_products: List[str]
    status: str
    created_at: datetime


# ============ Financing ============

class FinancingScoreResponse(BaseModel):
    enterprise_id: uuid.UUID
    score: int
    level: str
    estimated_loan_amount: Decimal
    matched_products: List[dict]
    scoring_factors: List[dict]


# ============ Files ============

class FileUploadResponse(BaseModel):
    file_id: uuid.UUID
    file_name: str
    file_size: int
    content_type: str
    url: str


# ============ Error ============

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
