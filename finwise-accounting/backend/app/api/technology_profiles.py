from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.technology_profile import (
    TechnologyProfileRead,
    TechnologyScanItemCompleteInput,
    TechnologyScanItemFailureInput,
    TechnologyScanJobCreate,
    TechnologyScanJobListRead,
    TechnologyScanJobPauseInput,
    TechnologyScanJobRead,
    TechnologyScanResultInput,
    TechnologyTagRead,
)
from app.services.enterprise_service import NotFoundError, ValidationError
from app.services.technology_scan_job_service import (
    complete_item,
    create_scan_job,
    fail_item,
    get_scan_job,
    list_scan_jobs,
    mark_item_running,
    pause_job,
    serialize_job,
)
from app.services.technology_profile_service import (
    confirm_tag,
    get_or_create_profile,
    reject_tag,
    serialize_profile,
    upsert_scan_results,
)


router = APIRouter(tags=["technology-profiles"])


@router.get("/api/enterprises/{enterprise_id}/technology-profile", response_model=TechnologyProfileRead)
def get_technology_profile_endpoint(enterprise_id: UUID, db: Session = Depends(get_db)):
    return _handle_service_errors(lambda: serialize_profile(*get_or_create_profile(db, enterprise_id)))


@router.post("/api/enterprises/{enterprise_id}/technology-profile/scan-results", response_model=TechnologyProfileRead)
def upsert_technology_scan_results_endpoint(
    enterprise_id: UUID,
    payload: TechnologyScanResultInput,
    db: Session = Depends(get_db),
):
    return _handle_service_errors(lambda: serialize_profile(*upsert_scan_results(db, enterprise_id, payload)))


@router.post("/api/technology-scan-jobs", response_model=TechnologyScanJobRead)
def create_technology_scan_job_endpoint(payload: TechnologyScanJobCreate, db: Session = Depends(get_db)):
    return _handle_service_errors(lambda: serialize_job(*create_scan_job(db, payload)))


@router.get("/api/technology-scan-jobs", response_model=TechnologyScanJobListRead)
def list_technology_scan_jobs_endpoint(db: Session = Depends(get_db)):
    return _handle_service_errors(
        lambda: {"jobs": [serialize_job(job, items) for job, items in list_scan_jobs(db)]}
    )


@router.get("/api/technology-scan-jobs/{job_id}", response_model=TechnologyScanJobRead)
def get_technology_scan_job_endpoint(job_id: UUID, db: Session = Depends(get_db)):
    return _handle_service_errors(lambda: serialize_job(*get_scan_job(db, job_id)))


@router.post("/api/technology-scan-jobs/{job_id}/items/{item_id}/mark-running", response_model=TechnologyScanJobRead)
def mark_technology_scan_item_running_endpoint(job_id: UUID, item_id: UUID, db: Session = Depends(get_db)):
    return _handle_service_errors(lambda: serialize_job(*mark_item_running(db, job_id, item_id)))


@router.post("/api/technology-scan-jobs/{job_id}/items/{item_id}/complete", response_model=TechnologyScanJobRead)
def complete_technology_scan_item_endpoint(
    job_id: UUID,
    item_id: UUID,
    payload: TechnologyScanItemCompleteInput,
    db: Session = Depends(get_db),
):
    return _handle_service_errors(lambda: serialize_job(*complete_item(db, job_id, item_id, payload)))


@router.post("/api/technology-scan-jobs/{job_id}/items/{item_id}/fail", response_model=TechnologyScanJobRead)
def fail_technology_scan_item_endpoint(
    job_id: UUID,
    item_id: UUID,
    payload: TechnologyScanItemFailureInput,
    db: Session = Depends(get_db),
):
    return _handle_service_errors(lambda: serialize_job(*fail_item(db, job_id, item_id, payload)))


@router.post("/api/technology-scan-jobs/{job_id}/pause", response_model=TechnologyScanJobRead)
def pause_technology_scan_job_endpoint(
    job_id: UUID,
    payload: TechnologyScanJobPauseInput,
    db: Session = Depends(get_db),
):
    return _handle_service_errors(lambda: serialize_job(*pause_job(db, job_id, payload)))


@router.post("/api/technology-tags/{tag_id}/confirm", response_model=TechnologyTagRead)
def confirm_technology_tag_endpoint(tag_id: UUID, db: Session = Depends(get_db)):
    return _handle_service_errors(lambda: confirm_tag(db, tag_id))


@router.post("/api/technology-tags/{tag_id}/reject", response_model=TechnologyTagRead)
def reject_technology_tag_endpoint(tag_id: UUID, db: Session = Depends(get_db)):
    return _handle_service_errors(lambda: reject_tag(db, tag_id))


def _handle_service_errors(action: Callable[[], object]):
    try:
        return action()
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
