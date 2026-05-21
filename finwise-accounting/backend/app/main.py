from fastapi import FastAPI

from app import models  # noqa: F401
from app.core.database import Base, SessionLocal, engine
from app.core.org_context import ensure_default_organization


def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_default_organization(db)

    app = FastAPI(title="FinWise Accounting API")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
