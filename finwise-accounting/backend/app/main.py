from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app import models  # noqa: F401
from app.api.enterprises import router as enterprises_router
from app.api.historical_imports import router as historical_imports_router
from app.api.initial_statements import router as initial_statements_router
from app.api.imports import router as imports_router
from app.api.ledgers import router as ledgers_router
from app.api.matching import router as matching_router
from app.api.reports import router as reports_router
from app.api.statements import router as statements_router
from app.api.tax import router as tax_router
from app.api.technology_profiles import router as technology_profiles_router
from app.api.vouchers import router as vouchers_router
from app.api.workspace import router as workspace_router
from app.core.database import Base, SessionLocal, engine
from app.core.org_context import ensure_default_organization


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            _ensure_sqlite_column(connection, "technology_scan_jobs", "scope_type", "VARCHAR(32) DEFAULT 'UNSCANNED'")
            _ensure_sqlite_column(connection, "technology_scan_jobs", "review_required_count", "INTEGER DEFAULT 0")
            _ensure_sqlite_column(connection, "technology_scan_jobs", "created_by", "VARCHAR(80) DEFAULT 'operator'")
            _ensure_sqlite_column(connection, "technology_scan_jobs", "updated_at", "DATETIME")
            for table_name in ("historical_import_batches", "historical_ledger_entries", "historical_balance_rows"):
                _ensure_sqlite_column(connection, table_name, "period_start_month", "INTEGER DEFAULT 1")
                _ensure_sqlite_column(connection, table_name, "period_end_month", "INTEGER DEFAULT 12")
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_initial_snapshots_org_enterprise_idx "
                "ON initial_financial_snapshots (organization_id, enterprise_id)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_match_records_package_transaction_invoice_idx "
                "ON match_records (monthly_work_package_id, bank_transaction_id, invoice_id) "
                "WHERE bank_transaction_id IS NOT NULL AND invoice_id IS NOT NULL"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_accounting_lines_package_source_business_idx "
                "ON accounting_lines (monthly_work_package_id, source_type, source_id, business_type)"
            )
        )
    with SessionLocal() as db:
        ensure_default_organization(db)


def _ensure_sqlite_column(connection, table_name: str, column_name: str, definition: str) -> None:
    columns = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table_name})"))}
    if column_name not in columns:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    initialize_database()
    yield


def create_app(*, init_db_on_startup: bool = True) -> FastAPI:
    app_kwargs = {"title": "FinWise Accounting API"}
    if init_db_on_startup:
        app_kwargs["lifespan"] = lifespan

    app = FastAPI(**app_kwargs)
    app.include_router(enterprises_router)
    app.include_router(historical_imports_router)
    app.include_router(initial_statements_router)
    app.include_router(imports_router)
    app.include_router(ledgers_router)
    app.include_router(matching_router)
    app.include_router(reports_router)
    app.include_router(statements_router)
    app.include_router(tax_router)
    app.include_router(technology_profiles_router)
    app.include_router(vouchers_router)
    app.include_router(workspace_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
