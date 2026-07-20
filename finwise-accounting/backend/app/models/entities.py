from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
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


class TechnologyProfile(Base):
    __tablename__ = "technology_profiles"
    __table_args__ = (UniqueConstraint("organization_id", "enterprise_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    enterprise_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("enterprises.id"), index=True)
    overall_status: Mapped[str] = mapped_column(String(32), default="NOT_SCANNED")
    primary_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    next_rescan_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    raw_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TechnologyTag(Base):
    __tablename__ = "technology_tags"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "enterprise_id",
            "category",
            "name",
            "source_provider",
            name="uq_technology_tags_enterprise_category_name_provider",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_technology_tags_confidence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    enterprise_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("enterprises.id"), index=True)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("technology_profiles.id"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    value: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    source_provider: Mapped[str] = mapped_column(String(32))
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_text: Mapped[str] = mapped_column(Text, default="")
    evidence_file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TechnologyScanJob(Base):
    __tablename__ = "technology_scan_jobs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    scope_type: Mapped[str] = mapped_column(String(32), default="UNSCANNED")
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    target_enterprise_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_enterprise_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_enterprise_count: Mapped[int] = mapped_column(Integer, default=0)
    review_required_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(80), default="operator")
    error_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TechnologyScanJobItem(Base):
    __tablename__ = "technology_scan_job_items"
    __table_args__ = (UniqueConstraint("job_id", "enterprise_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("technology_scan_jobs.id"), index=True)
    enterprise_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("enterprises.id"), index=True)
    enterprise_name: Mapped[str] = mapped_column(String(160))
    unified_social_credit_code: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    failure_reason: Mapped[str] = mapped_column(String(60), default="")
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    raw_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    error_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InitialFinancialSnapshot(Base):
    __tablename__ = "initial_financial_snapshots"
    __table_args__ = (UniqueConstraint("organization_id", "enterprise_id"),)

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


class VoucherAiPreprocessJob(Base):
    __tablename__ = "voucher_ai_preprocess_jobs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monthly_work_packages.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    model: Mapped[str] = mapped_column(String(80), default="")
    input_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    input_bank_count: Mapped[int] = mapped_column(Integer, default=0)
    input_invoice_count: Mapped[int] = mapped_column(Integer, default=0)
    total_batches: Mapped[int] = mapped_column(Integer, default=0)
    completed_batches: Mapped[int] = mapped_column(Integer, default=0)
    failed_batches: Mapped[int] = mapped_column(Integer, default=0)
    created_vouchers: Mapped[int] = mapped_column(Integer, default=0)
    analysis_summary: Mapped[str] = mapped_column(Text, default="")
    error_summary: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VoucherAiPreprocessBatch(Base):
    __tablename__ = "voucher_ai_preprocess_batches"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("voucher_ai_preprocess_jobs.id"), index=True)
    parent_batch_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("voucher_ai_preprocess_batches.id"), nullable=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    suggestions: Mapped[list] = mapped_column(JSON, default=list)
    analysis_summary: Mapped[str] = mapped_column(Text, default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    error_summary: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AccountSubject(Base):
    __tablename__ = "account_subjects"
    __table_args__ = (
        UniqueConstraint("organization_id", "enterprise_id", "code", name="uq_account_subjects_enterprise_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    enterprise_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("enterprises.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(32))
    normal_balance: Mapped[str] = mapped_column(String(12))
    parent_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_leaf: Mapped[bool] = mapped_column(Boolean, default=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_voucher: Mapped[bool] = mapped_column(Boolean, default=True)
    is_common: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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


class HistoricalImportBatch(Base):
    __tablename__ = "historical_import_batches"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    enterprise_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("enterprises.id"), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    period_start_month: Mapped[int] = mapped_column(Integer, default=1)
    period_end_month: Mapped[int] = mapped_column(Integer, default=12)
    source_standard: Mapped[str] = mapped_column(String(40), default="GB/T24589-2010")
    ledger_filename: Mapped[str] = mapped_column(String(240))
    balance_filename: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(24), default="IMPORTED")
    created_ledger_rows: Mapped[int] = mapped_column(Integer, default=0)
    created_balance_rows: Mapped[int] = mapped_column(Integer, default=0)
    replaced_ledger_rows: Mapped[int] = mapped_column(Integer, default=0)
    replaced_balance_rows: Mapped[int] = mapped_column(Integer, default=0)
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    file_hashes: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HistoricalLedgerEntry(Base):
    __tablename__ = "historical_ledger_entries"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    enterprise_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("enterprises.id"), index=True)
    import_batch_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("historical_import_batches.id"), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    period_start_month: Mapped[int] = mapped_column(Integer, default=1)
    period_end_month: Mapped[int] = mapped_column(Integer, default=12)
    voucher_date: Mapped[date] = mapped_column(Date)
    voucher_no: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(Text)
    account_full_name: Mapped[str] = mapped_column(String(240))
    account_code: Mapped[str] = mapped_column(String(32), index=True)
    account_name: Mapped[str] = mapped_column(String(120))
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    auxiliary: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_row_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HistoricalBalanceRow(Base):
    __tablename__ = "historical_balance_rows"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    enterprise_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("enterprises.id"), index=True)
    import_batch_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("historical_import_batches.id"), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    period_start_month: Mapped[int] = mapped_column(Integer, default=1)
    period_end_month: Mapped[int] = mapped_column(Integer, default=12)
    account_code: Mapped[str] = mapped_column(String(32), index=True)
    account_name: Mapped[str] = mapped_column(String(120))
    opening_debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    opening_credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    period_debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    period_credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    closing_debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    closing_credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    raw_row_data: Mapped[dict] = mapped_column(JSON, default=dict)
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
        UniqueConstraint(
            "monthly_work_package_id",
            "bank_transaction_id",
            "invoice_id",
            name="uq_match_records_package_transaction_invoice",
        ),
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
    __table_args__ = (
        UniqueConstraint(
            "monthly_work_package_id",
            "source_type",
            "source_id",
            "business_type",
            name="uq_accounting_lines_package_source_business",
        ),
    )

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


class VoucherRule(Base):
    __tablename__ = "voucher_rules"
    __table_args__ = (
        UniqueConstraint("organization_id", "enterprise_id", "rule_name", name="uq_voucher_rules_enterprise_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    enterprise_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("enterprises.id"), index=True)
    rule_name: Mapped[str] = mapped_column(String(120))
    summary_keywords: Mapped[list] = mapped_column(JSON, default=list)
    counterparty_pattern: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    source_direction: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    invoice_direction: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    summary_template: Mapped[str] = mapped_column(String(160))
    debit_account_code: Mapped[str] = mapped_column(String(32))
    credit_account_code: Mapped[str] = mapped_column(String(32))
    tax_account_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    require_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Voucher(Base):
    __tablename__ = "vouchers"
    __table_args__ = (
        UniqueConstraint("monthly_work_package_id", "source_key", name="uq_vouchers_package_source_key"),
        CheckConstraint("ai_confidence >= 0 AND ai_confidence <= 100", name="ck_vouchers_ai_confidence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monthly_work_packages.id"), index=True
    )
    voucher_date: Mapped[date] = mapped_column(Date)
    voucher_number: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    summary: Mapped[str] = mapped_column(String(180))
    attachment_count: Mapped[int] = mapped_column(Integer, default=0)
    source_key: Mapped[str] = mapped_column(String(160))
    source_data: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_confidence: Mapped[int] = mapped_column(Integer, default=0)
    ai_reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="PENDING_CONFIRMATION")
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    entries: Mapped[list["VoucherEntry"]] = relationship(
        "VoucherEntry",
        back_populates="voucher",
        cascade="all, delete-orphan",
        order_by="VoucherEntry.line_no",
    )


class VoucherEntry(Base):
    __tablename__ = "voucher_entries"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    voucher_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("vouchers.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(String(8))
    account_code: Mapped[str] = mapped_column(String(32))
    account_name: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))

    voucher: Mapped[Voucher] = relationship("Voucher", back_populates="entries")


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
