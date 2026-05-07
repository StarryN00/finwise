"""
Files Router - handles file upload, download, and delete.
"""
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from backend.core.config import settings
from backend.models.schemas import FileUploadResponse
from backend.services.file_service import file_service

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """Upload a file. Returns file_id and URL."""
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large. Max: {settings.MAX_FILE_SIZE // (1024*1024)}MB")
    await file.seek(0)
    file_id, url = await file_service.save_upload(file)
    return FileUploadResponse(
        file_id=file_id,
        file_name=file.filename or "unknown",
        file_size=len(content),
        content_type=file.content_type or "application/octet-stream",
        url=url,
    )


@router.get("/{file_id}")
async def download_file(file_id: uuid.UUID, filename: Optional[str] = None):
    """Download a file by ID."""
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")
    path = file_service.get_file_path(file_id, filename)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=path, filename=filename, media_type="application/octet-stream")


@router.delete("/{file_id}")
async def delete_file(file_id: uuid.UUID, filename: str):
    """Delete a file."""
    deleted = file_service.delete_file(file_id, filename)
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")
    return {"message": "File deleted successfully"}
