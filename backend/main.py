"""
FinWise Backend - 智税管家 FastAPI Application
"""
import os
import sys
from pathlib import Path

# Ensure backend is in path
sys.path.insert(0, str(Path(__file__).parent))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.storage.manager import enterprise_store, user_store

# Import routers
from backend.routers import auth, enterprises, imports, parse, files, tax, reports


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="智税管家 - 企业全生命周期服务 SaaS 平台",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# CORS
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

from fastapi.staticfiles import StaticFiles

# Mount static files for uploads
if settings.FILES_DIR.exists():
    app.mount("/files", StaticFiles(directory=str(settings.FILES_DIR)), name="files")

# Include routers
app.include_router(auth.router)
app.include_router(enterprises.router)
app.include_router(imports.router)
app.include_router(parse.router)
app.include_router(files.router)
app.include_router(tax.router)
app.include_router(reports.router)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "app": settings.APP_NAME,
        "storage": "json",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
