from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.workspace_service import get_workspace_snapshot


router = APIRouter(tags=["workspace"])


@router.get("/api/workspace")
def workspace_snapshot_endpoint(package_id: UUID | None = None, db: Session = Depends(get_db)):
    return get_workspace_snapshot(db, selected_package_id=package_id)
