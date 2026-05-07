"""
File storage service - handles upload/download/delete of files.
Phase 1: local disk storage. Later: Aliyun OSS.
"""
import uuid
import shutil
from pathlib import Path
from typing import Optional

from fastapi import UploadFile

from backend.core.config import settings


class FileService:
    FILES_DIR = settings.FILES_DIR

    @classmethod
    async def save_upload(cls, file: UploadFile, subfolder: str = "") -> tuple[uuid.UUID, str]:
        """
        Save an uploaded file to local disk.
        Returns (file_id, relative_url).
        """
        file_id = uuid.uuid4()
        ext = Path(file.filename or "bin").suffix.lower()

        folder = cls.FILES_DIR / subfolder if subfolder else cls.FILES_DIR
        folder.mkdir(parents=True, exist_ok=True)

        dest = folder / f"{file_id}{ext}"
        shutil.copyfileobj(file.file, dest.open("wb"))

        relative_url = f"/files/{subfolder}/{file_id}{ext}" if subfolder else f"/files/{file_id}{ext}"
        return file_id, relative_url

    @classmethod
    def get_file_path(cls, file_id: uuid.UUID, filename: str) -> Optional[Path]:
        """Get absolute path for a file by ID and original filename."""
        # Try to find the file in FILES_DIR
        file_ext = Path(filename).suffix.lower()
        possible = cls.FILES_DIR / f"{file_id}{file_ext}"
        if possible.exists():
            return possible

        # Search recursively
        for p in cls.FILES_DIR.rglob(f"{file_id}.*"):
            return p
        return None

    @classmethod
    def delete_file(cls, file_id: uuid.UUID, filename: str) -> bool:
        """Delete a file. Returns True if deleted."""
        path = cls.get_file_path(file_id, filename)
        if path and path.exists():
            path.unlink()
            return True
        return False


file_service = FileService()
