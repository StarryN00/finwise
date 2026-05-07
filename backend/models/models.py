import uuid
from datetime import datetime, date
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional, List

from sqlalchemy import (
    Column, String, Integer, DateTime, Date, ForeignKey,
    Numeric, Text, Enum, Index, JSON, Boolean
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from backend.core.database import Base


class UserStatus(PyEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class UserRole(PyEnum):
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"


class EnterpriseStatus(PyEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class EnterpriseSource(PyEnum):
    DIRECT = "DIRECT"
    LIU = "LIU"
    PING = "PING"


class TaxpayerType(PyEnum):
    GENERAL = "GENERAL"
    SMALL = "SMALL"


class InvoiceType(PyEnum):
    VAT_SPECIAL = "VAT_SPECIAL"
    VAT_NORMAL = "VAT_NORMAL"


class InvoiceStatus(PyEnum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    ANOMALY = "ANOMALY"


class TransactionStatus(PyEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DELETED = "DELETED"


class StatementType(PyEnum):
    BALANCE_SHEET = "BALANCE_SHEET"
    INCOME = "INCOME"
    CASH_FLOW = "CASH_FLOW"


class ImportType(PyEnum):
    INVOICE = "INVOICE"
    BANK_STATEMENT = "BANK_STATEMENT"
    FINANCIAL_STATEMENT = "FINANCIAL_STATEMENT"


class ImportStatus(PyEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class VATStatus(PyEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    FILED = "FILED"


class HealthReportStatus(PyEnum):
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class HealthGrade(PyEnum):
    A_PLUS = "A_PLUS"
    A = "A"
    B_PLUS = "B_PLUS"
    B = "B"
    C = "C"
    D = "D"


class FinancingLevel(PyEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    real_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.OPERATOR)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    enterprises: Mapped[List["Enterprise"]] = relationship("Enterprise", back_populates="operator")


class Enterprise(Base):
    __tablename__ = "enterprises"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tax_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    taxpayer_type: Mapped[TaxpayerType] = mapped_column(Enum(TaxpayerType), default=TaxpayerType.GENERAL)
    industry: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    registered_capital_range: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    founded_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    province: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source: Mapped[EnterpriseSource] = mapped_column(Enum(EnterpriseSource), default=EnterpriseSource.DIRECT)
    assigned_operator_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status: Mapped[EnterpriseStatus] = mapped_column(Enum(EnterpriseStatus), default=EnterpriseStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    operator: Mapped[Optional["User"]] = relationship("User", back_populates="enterprises")
    invoices: Mapped[List["Invoice"]] = relationship("Invoice", back_populates="enterprise")
    bank_transactions: Mapped[List["BankTransaction"]] = relationship("BankTransaction", back_populates="enterprise")
    financial_statements: Mapped[List["FinancialStatement"]] = relationship("FinancialStatement", back_populates="enterprise")
    vat_filings: Mapped[List["VATFiling"]] = relationship("VATFiling", back_populates="enterprise")
    health_reports: Mapped[List["HealthReport"]] = relationship("HealthReport", back_populates="enterprise")
    import_batches: Mapped[List["ImportBatch"]] = relationship("ImportBatch", back_populates="enterprise")

    __table_args__ = (
        Index("idx_enterprises_channel_id", "channel_id"),
        Index("idx_enterprises_source", "source"),
    )


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False)
    import_type: Mapped[ImportType] = mapped_column(Enum(ImportType), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    processed_rows: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[ImportStatus] = mapped_column(Enum(ImportStatus), default=ImportStatus.PENDING)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    enterprise: Mapped["Enterprise"] = relationship("Enterprise", back_populates="import_batches")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    invoice_type: Mapped[InvoiceType] = mapped_column(Enum(InvoiceType), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    seller_name: Mapped[str] = mapped_column(String(200), nullable=False)
    seller_tax_number: Mapped[str] = mapped_column(String(50), nullable=False)
    buyer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    buyer_tax_number: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(Enum(InvoiceStatus), default=InvoiceStatus.PENDING)
    import_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    enterprise: Mapped["Enterprise"] = relationship("Enterprise", back_populates="invoices")
    import_batch: Mapped[Optional["ImportBatch"]] = relationship("ImportBatch")

    __table_args__ = (
        Index("idx_invoices_enterprise_id", "enterprise_id"),
        Index("idx_invoices_issue_date", "issue_date"),
    )


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    debit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    credit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    account_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    status: Mapped[TransactionStatus] = mapped_column(Enum(TransactionStatus), default=TransactionStatus.PENDING)
    matched_invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=True)
    import_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    enterprise: Mapped["Enterprise"] = relationship("Enterprise", back_populates="bank_transactions")
    matched_invoice: Mapped[Optional["Invoice"]] = relationship("Invoice")

    __table_args__ = (
        Index("idx_bank_tx_enterprise_id", "enterprise_id"),
        Index("idx_bank_tx_date", "transaction_date"),
        Index("idx_bank_tx_matched_invoice", "matched_invoice_id"),
    )


class FinancialStatement(Base):
    __tablename__ = "financial_statements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False)
    statement_type: Mapped[StatementType] = mapped_column(Enum(StatementType), nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    import_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    enterprise: Mapped["Enterprise"] = relationship("Enterprise", back_populates="financial_statements")


class VATFiling(Base):
    __tablename__ = "vat_filings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    taxpayer_type: Mapped[TaxpayerType] = mapped_column(Enum(TaxpayerType), nullable=False)
    sales_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    surcharge_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[VATStatus] = mapped_column(Enum(VATStatus), default=VATStatus.DRAFT)
    excel_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    enterprise: Mapped["Enterprise"] = relationship("Enterprise", back_populates="vat_filings")


class HealthReport(Base):
    __tablename__ = "health_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False)
    report_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    analysis_date: Mapped[date] = mapped_column(Date, nullable=False)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    overall_grade: Mapped[HealthGrade] = mapped_column(Enum(HealthGrade), nullable=False)
    profitability_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    solvency_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    operation_efficiency_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    growth_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    cash_flow_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    radar_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    key_metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    ai_interpretation: Mapped[str] = mapped_column(Text, nullable=True)
    risk_alerts: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    improvement_suggestions: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    financing_score: Mapped[int] = mapped_column(Integer, nullable=True)
    estimated_loan_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    matched_products: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    pdf_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    html_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[HealthReportStatus] = mapped_column(Enum(HealthReportStatus), default=HealthReportStatus.GENERATING)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    enterprise: Mapped["Enterprise"] = relationship("Enterprise", back_populates="health_reports")

    __table_args__ = (
        Index("idx_health_reports_enterprise_id", "enterprise_id"),
        Index("idx_health_reports_date", "analysis_date"),
    )


class AIParseLog(Base):
    __tablename__ = "ai_parse_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False)
    import_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=False)
    parse_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "bank_statement", "match"
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, nullable=False)  # desensitized summary
    output_summary: Mapped[str] = mapped_column(Text, nullable=False)  # desensitized summary
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    enterprise_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
