from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app import models  # noqa: F401
from app.api.enterprises import router as enterprises_router
from app.api.imports import router as imports_router
from app.api.matching import router as matching_router
from app.api.reports import router as reports_router
from app.api.statements import router as statements_router
from app.api.tax import router as tax_router
from app.api.workspace import router as workspace_router
from app.core.database import Base, SessionLocal, engine
from app.core.org_context import ensure_default_organization


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
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
    app.include_router(imports_router)
    app.include_router(matching_router)
    app.include_router(reports_router)
    app.include_router(statements_router)
    app.include_router(tax_router)
    app.include_router(workspace_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
