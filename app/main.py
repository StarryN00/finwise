from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.auth import router as auth_router
from app.config import Settings
from app.db import Database
from app.ontology.errors import DomainError
from app.ontology.store import ObjectStore
from app.ontology.service import OntologyService


def create_app(settings: Optional[Settings] = None, *, initialize: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    def initialize_runtime(app: FastAPI) -> None:
        settings.validate_runtime()
        database = Database(settings)
        database.initialize()
        app.state.database = database
        app.state.store = ObjectStore(database)
        app.state.service = OntologyService(app.state.store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not hasattr(app.state, "database"):
            initialize_runtime(app)
        app.state.service.historical.start()
        app.state.service.payroll_mapping.start()
        app.state.service.problem_review.start()
        try:
            yield
        finally:
            app.state.service.historical.stop()
            app.state.service.payroll_mapping.stop()
            app.state.service.problem_review.stop()

    app = FastAPI(title="FinWise Ontology Finance System", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["null", "http://127.0.0.1:8766", "http://localhost:8766"], allow_methods=["*"], allow_headers=["*"])
    app.state.settings = settings
    if initialize:
        initialize_runtime(app)
    app.include_router(router)
    app.include_router(auth_router)

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(KeyError)
    async def key_error_handler(_: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": {"code": "NOT_FOUND", "message": str(exc).strip("'")}})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{key: item[key] for key in ("loc", "msg", "type")} for item in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_ERROR", "message": "请求未通过契约校验", "details": details}})

    static_dir = settings.root / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/styles.css", include_in_schema=False)
    def root_stylesheet() -> FileResponse:
        return FileResponse(static_dir / "styles.css", media_type="text/css")

    @app.get("/app.js", include_in_schema=False)
    def root_script() -> FileResponse:
        return FileResponse(static_dir / "app.js", media_type="application/javascript")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    return app


# Importing modules (including tests and tooling) must not touch the default database.
app = create_app(initialize=False)
