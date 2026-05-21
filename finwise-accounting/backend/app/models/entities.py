from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.core.database import Base


DEFAULT_CHANNEL_ID = UUID("00000000-0000-0000-0000-000000000001")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    name: Mapped[str] = mapped_column(String(120), default="默认代账机构")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Enterprise(Base):
    __tablename__ = "enterprises"
    __table_args__ = (UniqueConstraint("organization_id", "unified_social_credit_code"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    unified_social_credit_code: Mapped[str] = mapped_column(String(32), index=True)
    taxpayer_type: Mapped[str] = mapped_column(String(20))
    industry: Mapped[str] = mapped_column(String(80))
    province: Mapped[str] = mapped_column(String(40), default="江苏省")
    city: Mapped[str] = mapped_column(String(40), default="苏州市")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InitialFinancialSnapshot(Base):
    __tablename__ = "initial_financial_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    enterprise_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("enterprises.id"), index=True)
    balance_sheet_data: Mapped[dict] = mapped_column(JSON, default=dict)
    income_statement_data: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MonthlyWorkPackage(Base):
    __tablename__ = "monthly_work_packages"
    __table_args__ = (
        UniqueConstraint("organization_id", "enterprise_id", "period_year", "period_month"),
        CheckConstraint("period_month >= 1 AND period_month <= 12", name="ck_monthly_work_packages_period_month"),
        CheckConstraint(
            "completion_percent >= 0 AND completion_percent <= 100",
            name="ck_monthly_work_packages_completion_percent",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    enterprise_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("enterprises.id"), index=True)
    period_year: Mapped[int] = mapped_column(Integer)
    period_month: Mapped[int] = mapped_column(Integer)
    data_status: Mapped[str] = mapped_column(String(24), default="PENDING_IMPORT")
    matching_status: Mapped[str] = mapped_column(String(24), default="NOT_STARTED")
    filing_status: Mapped[str] = mapped_column(String(24), default="NOT_STARTED")
    report_status: Mapped[str] = mapped_column(String(24), default="NOT_STARTED")
    pending_confirmation_count: Mapped[int] = mapped_column(Integer, default=0)
    completion_percent: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monthly_work_packages.id"), index=True
    )
    file_type: Mapped[str] = mapped_column(String(32))
    original_filename: Mapped[str] = mapped_column(String(240))
    stored_path: Mapped[str] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String(24), default="PENDING")
    field_mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    error_rows: Mapped[list] = mapped_column(JSON, default=list)
    import_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        CheckConstraint(
            "parse_confidence >= 0 AND parse_confidence <= 100",
            name="ck_bank_transactions_parse_confidence",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monthly_work_packages.id"), index=True
    )
    import_batch_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_batches.id"), nullable=True
    )
    transaction_date: Mapped[date] = mapped_column(Date)
    summary: Mapped[str] = mapped_column(Text)
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    counterparty_name: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    counterparty_account: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    raw_row_data: Mapped[dict] = mapped_column(JSON, default=dict)
    parse_confidence: Mapped[int] = mapped_column(Integer, default=100)
    processing_status: Mapped[str] = mapped_column(String(24), default="PENDING")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monthly_work_packages.id"), index=True
    )
    import_batch_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_batches.id"), nullable=True
    )
    invoice_direction: Mapped[str] = mapped_column(String(12))
    invoice_number: Mapped[str] = mapped_column(String(80), index=True)
    invoice_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    seller_name: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    buyer_name: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="NORMAL")
    raw_row_data: Mapped[dict] = mapped_column(JSON, default=dict)


class MatchRecord(Base):
    __tablename__ = "match_records"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_match_records_confidence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monthly_work_packages.id"), index=True
    )
    bank_transaction_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("bank_transactions.id"), nullable=True
    )
    invoice_id: Mapped[Optional[UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("invoices.id"), nullable=True)
    match_group_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    match_method: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    explanation: Mapped[str] = mapped_column(Text, default="")
    confirmation_status: Mapped[str] = mapped_column(String(24), default="AUTO_CONFIRMED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AccountingLine(Base):
    __tablename__ = "accounting_lines"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monthly_work_packages.id"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))
    business_type: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    include_category: Mapped[str] = mapped_column(String(32))
    confirmation_status: Mapped[str] = mapped_column(String(24), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MatchingRule(Base):
    __tablename__ = "matching_rules"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    enterprise_id: Mapped[Optional[UUID]] = mapped_column(Uuid(as_uuid=True), ForeignKey("enterprises.id"), nullable=True)
    scope: Mapped[str] = mapped_column(String(24))
    summary_keywords: Mapped[list] = mapped_column(JSON, default=list)
    counterparty_pattern: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    min_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    max_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    invoice_direction: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    suggested_business_type: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(24), default="BUILT_IN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MonthlyStatement(Base):
    __tablename__ = "monthly_statements"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monthly_work_packages.id"), index=True
    )
    estimated_balance_sheet: Mapped[dict] = mapped_column(JSON, default=dict)
    estimated_income_statement: Mapped[dict] = mapped_column(JSON, default=dict)
    formal_balance_sheet: Mapped[dict] = mapped_column(JSON, default=dict)
    formal_income_statement: Mapped[dict] = mapped_column(JSON, default=dict)
    difference_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TaxFilingDraft(Base):
    __tablename__ = "tax_filing_drafts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monthly_work_packages.id"), index=True
    )
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    export_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monthly_work_packages.id"), index=True
    )
    report_type: Mapped[str] = mapped_column(String(32))
    data_version: Mapped[dict] = mapped_column(JSON, default=dict)
    html_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    export_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="GENERATED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    monthly_work_package_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monthly_work_packages.id"), nullable=True
    )
    actor: Mapped[str] = mapped_column(String(80), default="system")
    action: Mapped[str] = mapped_column(String(80))
    before_data: Mapped[dict] = mapped_column(JSON, default=dict)
    after_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
