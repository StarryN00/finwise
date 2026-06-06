from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.org_context import ensure_default_organization, get_current_organization_id
from app.models import DEFAULT_CHANNEL_ID, Enterprise, TechnologyProfile, TechnologyTag
from app.schemas.technology_profile import TechnologyScanResultInput
from app.services.enterprise_service import NotFoundError
from app.services.qichacha_innovation_parser import parse_qichacha_innovation_text


def get_or_create_profile(db: Session, enterprise_id: UUID) -> tuple[TechnologyProfile, list[TechnologyTag]]:
    organization_id = _ensure_current_organization(db)
    _get_enterprise(db, enterprise_id, organization_id)
    profile = db.scalar(
        select(TechnologyProfile).where(
            TechnologyProfile.organization_id == organization_id,
            TechnologyProfile.enterprise_id == enterprise_id,
        )
    )
    if profile is None:
        profile = TechnologyProfile(
            channel_id=DEFAULT_CHANNEL_ID,
            organization_id=organization_id,
            enterprise_id=enterprise_id,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile, _profile_tags(db, profile.id)


def upsert_scan_results(
    db: Session,
    enterprise_id: UUID,
    payload: TechnologyScanResultInput,
) -> tuple[TechnologyProfile, list[TechnologyTag]]:
    organization_id = _ensure_current_organization(db)
    _get_enterprise(db, enterprise_id, organization_id)
    payload = _normalize_scan_payload(payload)
    profile, _tags = get_or_create_profile(db, enterprise_id)
    provider = _normalize_code(payload.provider)
    now = datetime.utcnow()
    profile.primary_provider = provider
    profile.overall_status = "SCANNED_PENDING_REVIEW"
    profile.last_scanned_at = now
    profile.summary = payload.summary
    profile.raw_snapshot = payload.raw_snapshot

    for item in payload.tags:
        category = _normalize_code(item.category)
        name = item.name.strip()
        if not name:
            continue
        existing = db.scalar(
            select(TechnologyTag).where(
                TechnologyTag.organization_id == organization_id,
                TechnologyTag.enterprise_id == enterprise_id,
                TechnologyTag.category == category,
                TechnologyTag.name == name,
                TechnologyTag.source_provider == provider,
            )
        )
        if existing is None:
            existing = TechnologyTag(
                channel_id=DEFAULT_CHANNEL_ID,
                organization_id=organization_id,
                enterprise_id=enterprise_id,
                profile_id=profile.id,
                category=category,
                name=name,
                source_provider=provider,
            )
            db.add(existing)
        existing.profile_id = profile.id
        existing.status = _normalize_code(item.status)
        existing.value = item.value
        existing.confidence = item.confidence
        existing.source_url = item.source_url
        existing.evidence_text = item.evidence_text
        existing.evidence_file_path = item.evidence_file_path
    db.commit()
    db.refresh(profile)
    return profile, _profile_tags(db, profile.id)


def _normalize_scan_payload(payload: TechnologyScanResultInput) -> TechnologyScanResultInput:
    if not payload.qichacha_innovation_text:
        return payload

    parsed = parse_qichacha_innovation_text(payload.qichacha_innovation_text)
    raw_snapshot = {**parsed.get("raw_snapshot", {}), **payload.raw_snapshot}
    if payload.qichacha_innovation_text:
        raw_snapshot["qichacha_innovation_text"] = payload.qichacha_innovation_text
    tags = []
    for tag in parsed.get("tags", []):
        item = dict(tag)
        if payload.source_url and not item.get("source_url"):
            item["source_url"] = payload.source_url
        tags.append(item)

    return TechnologyScanResultInput(
        provider=payload.provider or parsed["provider"],
        source_url=payload.source_url,
        summary=payload.summary or parsed.get("summary", ""),
        raw_snapshot=raw_snapshot,
        tags=tags,
    )


def confirm_tag(db: Session, tag_id: UUID) -> TechnologyTag:
    tag = _get_tag(db, tag_id)
    tag.status = "HIT"
    tag.confirmed_by = "operator"
    tag.confirmed_at = datetime.utcnow()
    _refresh_profile_confirmation(db, tag.profile_id)
    db.commit()
    db.refresh(tag)
    return tag


def reject_tag(db: Session, tag_id: UUID) -> TechnologyTag:
    tag = _get_tag(db, tag_id)
    tag.status = "NOT_HIT"
    tag.confirmed_by = "operator"
    tag.confirmed_at = datetime.utcnow()
    _refresh_profile_confirmation(db, tag.profile_id)
    db.commit()
    db.refresh(tag)
    return tag


def serialize_profile(profile: TechnologyProfile, tags: list[TechnologyTag]) -> dict:
    return {
        "id": profile.id,
        "enterprise_id": profile.enterprise_id,
        "overall_status": profile.overall_status,
        "primary_provider": profile.primary_provider,
        "last_scanned_at": profile.last_scanned_at,
        "last_confirmed_at": profile.last_confirmed_at,
        "next_rescan_at": profile.next_rescan_at,
        "summary": profile.summary,
        "raw_snapshot": profile.raw_snapshot,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
        "tags": tags,
    }


def _refresh_profile_confirmation(db: Session, profile_id: UUID) -> None:
    profile = db.get(TechnologyProfile, profile_id)
    if profile is not None:
        profile.last_confirmed_at = datetime.utcnow()


def _get_tag(db: Session, tag_id: UUID) -> TechnologyTag:
    organization_id = _ensure_current_organization(db)
    tag = db.get(TechnologyTag, tag_id)
    if tag is None or tag.organization_id != organization_id:
        raise NotFoundError("Technology tag not found in current organization.")
    return tag


def _profile_tags(db: Session, profile_id: UUID) -> list[TechnologyTag]:
    return list(
        db.scalars(
            select(TechnologyTag)
            .where(TechnologyTag.profile_id == profile_id)
            .order_by(TechnologyTag.category, TechnologyTag.name, TechnologyTag.id)
        )
    )


def _get_enterprise(db: Session, enterprise_id: UUID, organization_id: UUID) -> Enterprise:
    enterprise = db.get(Enterprise, enterprise_id)
    if enterprise is None or enterprise.organization_id != organization_id:
        raise NotFoundError("Enterprise not found in current organization.")
    return enterprise


def _ensure_current_organization(db: Session) -> UUID:
    ensure_default_organization(db)
    return get_current_organization_id()


def _normalize_code(value: str) -> str:
    return (value or "").strip().upper()
