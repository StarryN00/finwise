from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.org_context import ensure_default_organization, get_current_organization_id
from app.models import DEFAULT_CHANNEL_ID, Enterprise, TechnologyProfile, TechnologyScanJob, TechnologyScanJobItem
from app.schemas.technology_profile import (
    TechnologyScanItemCompleteInput,
    TechnologyScanItemFailureInput,
    TechnologyScanJobCreate,
    TechnologyScanJobPauseInput,
    TechnologyScanResultInput,
)
from app.services.enterprise_service import NotFoundError, ValidationError
from app.services.technology_profile_service import upsert_scan_results


def create_scan_job(db: Session, payload: TechnologyScanJobCreate) -> tuple[TechnologyScanJob, list[TechnologyScanJobItem]]:
    organization_id = _ensure_current_organization(db)
    enterprises = _resolve_enterprises(db, organization_id, payload)
    if not enterprises:
        raise ValidationError("No enterprises matched the requested scan scope.")

    job = TechnologyScanJob(
        channel_id=DEFAULT_CHANNEL_ID,
        organization_id=organization_id,
        provider=_normalize_code(payload.provider),
        scope_type=_normalize_code(payload.scope_type),
        target_enterprise_count=len(enterprises),
        created_by="operator",
    )
    db.add(job)
    db.flush()
    for enterprise in enterprises:
        db.add(
            TechnologyScanJobItem(
                channel_id=DEFAULT_CHANNEL_ID,
                organization_id=organization_id,
                job_id=job.id,
                enterprise_id=enterprise.id,
                enterprise_name=enterprise.name,
                unified_social_credit_code=enterprise.unified_social_credit_code or "",
            )
        )
    db.commit()
    db.refresh(job)
    return job, _job_items(db, job.id)


def list_scan_jobs(db: Session) -> list[tuple[TechnologyScanJob, list[TechnologyScanJobItem]]]:
    organization_id = _ensure_current_organization(db)
    jobs = list(
        db.scalars(
            select(TechnologyScanJob)
            .where(TechnologyScanJob.organization_id == organization_id)
            .order_by(TechnologyScanJob.created_at.desc(), TechnologyScanJob.id.desc())
        )
    )
    return [(job, _job_items(db, job.id)) for job in jobs]


def get_scan_job(db: Session, job_id: UUID) -> tuple[TechnologyScanJob, list[TechnologyScanJobItem]]:
    job = _get_job(db, job_id)
    return job, _job_items(db, job.id)


def mark_item_running(db: Session, job_id: UUID, item_id: UUID) -> tuple[TechnologyScanJob, list[TechnologyScanJobItem]]:
    job = _get_job(db, job_id)
    item = _get_job_item(db, job, item_id)
    now = datetime.utcnow()
    item.status = "RUNNING"
    item.started_at = now
    item.failure_reason = ""
    item.error_summary = ""
    if job.status == "PENDING":
        job.status = "RUNNING"
        job.started_at = now
    _refresh_job_counts(db, job)
    db.commit()
    db.refresh(job)
    return job, _job_items(db, job.id)


def complete_item(
    db: Session,
    job_id: UUID,
    item_id: UUID,
    payload: TechnologyScanItemCompleteInput,
) -> tuple[TechnologyScanJob, list[TechnologyScanJobItem]]:
    job = _get_job(db, job_id)
    item = _get_job_item(db, job, item_id)
    provider = _normalize_code(job.provider)
    upsert_scan_results(
        db,
        item.enterprise_id,
        TechnologyScanResultInput(
            provider=provider,
            source_url=payload.source_url,
            qichacha_innovation_text=payload.qichacha_innovation_text,
            summary=payload.summary,
            raw_snapshot=payload.raw_snapshot,
            tags=payload.tags,
        ),
    )
    item.status = "COMPLETED"
    item.source_url = payload.source_url
    item.raw_snapshot = payload.raw_snapshot
    item.failure_reason = ""
    item.error_summary = ""
    item.completed_at = datetime.utcnow()
    _refresh_job_counts(db, job)
    db.commit()
    db.refresh(job)
    return job, _job_items(db, job.id)


def fail_item(
    db: Session,
    job_id: UUID,
    item_id: UUID,
    payload: TechnologyScanItemFailureInput,
) -> tuple[TechnologyScanJob, list[TechnologyScanJobItem]]:
    job = _get_job(db, job_id)
    item = _get_job_item(db, job, item_id)
    item.status = "NEEDS_REVIEW" if _normalize_code(payload.failure_reason) in REVIEW_REASONS else "FAILED"
    item.failure_reason = _normalize_code(payload.failure_reason)
    item.error_summary = payload.error_summary
    item.source_url = payload.source_url
    item.raw_snapshot = payload.raw_snapshot
    item.completed_at = datetime.utcnow()
    _refresh_job_counts(db, job)
    db.commit()
    db.refresh(job)
    return job, _job_items(db, job.id)


def pause_job(
    db: Session,
    job_id: UUID,
    payload: TechnologyScanJobPauseInput,
) -> tuple[TechnologyScanJob, list[TechnologyScanJobItem]]:
    job = _get_job(db, job_id)
    job.status = "PAUSED"
    job.error_summary = payload.error_summary or payload.failure_reason
    _refresh_job_counts(db, job)
    db.commit()
    db.refresh(job)
    return job, _job_items(db, job.id)


def serialize_job(job: TechnologyScanJob, items: list[TechnologyScanJobItem]) -> dict:
    return {
        "id": job.id,
        "provider": job.provider,
        "scope_type": job.scope_type,
        "status": job.status,
        "target_enterprise_count": job.target_enterprise_count,
        "completed_enterprise_count": job.completed_enterprise_count,
        "failed_enterprise_count": job.failed_enterprise_count,
        "review_required_count": job.review_required_count,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "created_by": job.created_by,
        "error_summary": job.error_summary,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "items": items,
    }


REVIEW_REASONS = {"LOGIN_REQUIRED", "CAPTCHA_REQUIRED", "AMBIGUOUS_MATCH", "NO_INNOVATION_PANEL"}


def _resolve_enterprises(db: Session, organization_id: UUID, payload: TechnologyScanJobCreate) -> list[Enterprise]:
    scope_type = _normalize_code(payload.scope_type)
    if scope_type == "SELECTED":
        if not payload.enterprise_ids:
            raise ValidationError("Selected scan jobs require enterprise_ids.")
        enterprises = list(
            db.scalars(
                select(Enterprise)
                .where(Enterprise.organization_id == organization_id, Enterprise.id.in_(payload.enterprise_ids))
                .order_by(Enterprise.created_at, Enterprise.id)
            )
        )
        if len(enterprises) != len(set(payload.enterprise_ids)):
            raise NotFoundError("One or more enterprises were not found in current organization.")
        return enterprises
    if scope_type == "UNSCANNED":
        scanned_ids = select(TechnologyProfile.enterprise_id).where(
            TechnologyProfile.organization_id == organization_id,
            TechnologyProfile.overall_status != "NOT_SCANNED",
        )
        return list(
            db.scalars(
                select(Enterprise)
                .where(Enterprise.organization_id == organization_id, Enterprise.id.not_in(scanned_ids))
                .order_by(Enterprise.created_at, Enterprise.id)
            )
        )
    if scope_type == "ALL":
        return list(
            db.scalars(
                select(Enterprise).where(Enterprise.organization_id == organization_id).order_by(Enterprise.created_at)
            )
        )
    if scope_type == "FAILED":
        failed_ids = select(TechnologyScanJobItem.enterprise_id).where(
            TechnologyScanJobItem.organization_id == organization_id,
            TechnologyScanJobItem.status.in_(["FAILED", "NEEDS_REVIEW"]),
        )
        return list(
            db.scalars(
                select(Enterprise)
                .where(Enterprise.organization_id == organization_id, Enterprise.id.in_(failed_ids))
                .order_by(Enterprise.created_at)
            )
        )
    raise ValidationError(f"Unsupported scan scope: {payload.scope_type}")


def _refresh_job_counts(db: Session, job: TechnologyScanJob) -> None:
    items = _job_items(db, job.id)
    job.target_enterprise_count = len(items)
    job.completed_enterprise_count = sum(1 for item in items if item.status == "COMPLETED")
    job.failed_enterprise_count = sum(1 for item in items if item.status == "FAILED")
    job.review_required_count = sum(1 for item in items if item.status == "NEEDS_REVIEW")
    if job.status != "PAUSED":
        if job.completed_enterprise_count == len(items):
            job.status = "COMPLETED"
            job.completed_at = datetime.utcnow()
        elif job.failed_enterprise_count or job.review_required_count:
            job.status = "PARTIAL_FAILED"
        elif any(item.status == "RUNNING" for item in items):
            job.status = "RUNNING"


def _get_job(db: Session, job_id: UUID) -> TechnologyScanJob:
    organization_id = _ensure_current_organization(db)
    job = db.get(TechnologyScanJob, job_id)
    if job is None or job.organization_id != organization_id:
        raise NotFoundError("Technology scan job not found in current organization.")
    return job


def _get_job_item(db: Session, job: TechnologyScanJob, item_id: UUID) -> TechnologyScanJobItem:
    item = db.get(TechnologyScanJobItem, item_id)
    if item is None or item.organization_id != job.organization_id or item.job_id != job.id:
        raise NotFoundError("Technology scan job item not found in current job.")
    return item


def _job_items(db: Session, job_id: UUID) -> list[TechnologyScanJobItem]:
    return list(
        db.scalars(
            select(TechnologyScanJobItem)
            .where(TechnologyScanJobItem.job_id == job_id)
            .order_by(TechnologyScanJobItem.created_at, TechnologyScanJobItem.id)
        )
    )


def _ensure_current_organization(db: Session) -> UUID:
    ensure_default_organization(db)
    return get_current_organization_id()


def _normalize_code(value: str) -> str:
    return (value or "").strip().upper()
