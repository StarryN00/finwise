from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app import models  # noqa: F401
from app.api.enterprises import router as enterprises_router
from app.api.imports import router as imports_router
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

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
