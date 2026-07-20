from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.org_context import get_current_organization_id
from app.models import (
    DEFAULT_CHANNEL_ID,
    Enterprise,
    MonthlyWorkPackage,
    VoucherAiPreprocessBatch,
    VoucherAiPreprocessJob,
)
from app.services.voucher_ai_preprocess_service import (
    MoonshotVoucherPreprocessClient,
    VoucherAiPreprocessUnavailableError,
    VoucherPreprocessClient,
    _apply_ai_match_suggestions,
    _attach_preprocess_metadata,
    _build_audit,
    _normalize_ai_response,
    _payload_ref_index,
    _retire_reassigned_single_source_vouchers,
    _source_ref_index,
    _task_counts,
    _write_audit_log,
    build_voucher_preprocess_payload,
)
from app.services.voucher_service import VoucherDomainError, VoucherValidationError, generate_voucher_drafts


ACTIVE_JOB_STATUSES = {"QUEUED", "RUNNING", "FINALIZING"}
RETRY_DELAYS_MINUTES = (1, 5, 15)
RUNNING_LEASE_SECONDS = 300


def create_voucher_preprocess_job(db: Session, *, monthly_work_package_id: UUID) -> VoucherAiPreprocessJob:
    organization_id = get_current_organization_id()
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None or package.organization_id != organization_id:
        raise VoucherDomainError("Monthly work package not found in current organization.")

    active_job = db.scalars(
        select(VoucherAiPreprocessJob)
        .where(
            VoucherAiPreprocessJob.organization_id == organization_id,
            VoucherAiPreprocessJob.monthly_work_package_id == package.id,
            VoucherAiPreprocessJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .order_by(VoucherAiPreprocessJob.created_at.desc(), VoucherAiPreprocessJob.id.desc())
    ).first()
    if active_job is not None:
        return active_job

    enterprise = db.get(Enterprise, package.enterprise_id)
    if enterprise is None or enterprise.organization_id != organization_id:
        raise VoucherDomainError("Enterprise not found.")
    payload = build_voucher_preprocess_payload(db, package=package, enterprise=enterprise)
    if not payload["bank_transactions"] and not payload["invoices"]:
        raise VoucherValidationError("当前工作包没有可进行 AI 预处理的流水或发票。")

    settings = get_settings()
    batch_payloads = _build_batch_payloads(payload, max_sources=settings.voucher_ai_batch_max_sources)
    job = VoucherAiPreprocessJob(
        channel_id=DEFAULT_CHANNEL_ID,
        organization_id=organization_id,
        monthly_work_package_id=package.id,
        model=settings.moonshot_model,
        input_fingerprint=_payload_fingerprint(payload),
        input_bank_count=len(payload["bank_transactions"]),
        input_invoice_count=len(payload["invoices"]),
        total_batches=len(batch_payloads),
    )
    db.add(job)
    db.flush()
    for sequence_no, batch_payload in enumerate(batch_payloads, start=1):
        db.add(
            VoucherAiPreprocessBatch(
                channel_id=DEFAULT_CHANNEL_ID,
                organization_id=organization_id,
                job_id=job.id,
                sequence_no=sequence_no,
                source_count=_source_count(batch_payload),
                payload=batch_payload,
            )
        )
    db.commit()
    db.refresh(job)
    return job


def get_voucher_preprocess_job(db: Session, *, job_id: UUID) -> VoucherAiPreprocessJob:
    job = db.get(VoucherAiPreprocessJob, job_id)
    if job is None or job.organization_id != get_current_organization_id():
        raise VoucherDomainError("Voucher preprocess job not found in current organization.")
    return job


def get_latest_voucher_preprocess_job(db: Session, *, monthly_work_package_id: UUID) -> VoucherAiPreprocessJob | None:
    organization_id = get_current_organization_id()
    return db.scalars(
        select(VoucherAiPreprocessJob)
        .where(
            VoucherAiPreprocessJob.organization_id == organization_id,
            VoucherAiPreprocessJob.monthly_work_package_id == monthly_work_package_id,
        )
        .order_by(VoucherAiPreprocessJob.created_at.desc(), VoucherAiPreprocessJob.id.desc())
    ).first()


def retry_voucher_preprocess_job(db: Session, *, job_id: UUID) -> VoucherAiPreprocessJob:
    job = get_voucher_preprocess_job(db, job_id=job_id)
    failed_batches = list(
        db.scalars(
            select(VoucherAiPreprocessBatch).where(
                VoucherAiPreprocessBatch.job_id == job.id,
                VoucherAiPreprocessBatch.status == "FAILED",
            )
        )
    )
    if not failed_batches:
        raise VoucherValidationError("当前任务没有可重试的失败批次。")
    for batch in failed_batches:
        batch.status = "QUEUED"
        batch.error_summary = ""
        batch.next_attempt_at = None
    job.status = "QUEUED"
    job.error_summary = ""
    job.completed_at = None
    _refresh_job_counts(db, job)
    db.commit()
    db.refresh(job)
    return job


def cancel_voucher_preprocess_job(db: Session, *, job_id: UUID) -> VoucherAiPreprocessJob:
    job = get_voucher_preprocess_job(db, job_id=job_id)
    if job.status not in ACTIVE_JOB_STATUSES:
        raise VoucherValidationError("当前任务无法取消。")
    for batch in db.scalars(
        select(VoucherAiPreprocessBatch).where(
            VoucherAiPreprocessBatch.job_id == job.id,
            VoucherAiPreprocessBatch.status.in_({"QUEUED", "RETRY_WAIT"}),
        )
    ):
        batch.status = "CANCELLED"
        batch.completed_at = datetime.utcnow()
    job.status = "CANCELLED"
    job.error_summary = "操作员已取消 AI 预处理任务。"
    job.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job


def serialize_voucher_preprocess_job(db: Session, job: VoucherAiPreprocessJob) -> dict:
    batches = list(
        db.scalars(
            select(VoucherAiPreprocessBatch)
            .where(VoucherAiPreprocessBatch.job_id == job.id)
            .order_by(VoucherAiPreprocessBatch.sequence_no, VoucherAiPreprocessBatch.created_at, VoucherAiPreprocessBatch.id)
        )
    )
    return {
        "id": job.id,
        "monthly_work_package_id": job.monthly_work_package_id,
        "status": job.status,
        "model": job.model,
        "input_bank_count": job.input_bank_count,
        "input_invoice_count": job.input_invoice_count,
        "total_batches": job.total_batches,
        "completed_batches": job.completed_batches,
        "failed_batches": job.failed_batches,
        "created_vouchers": job.created_vouchers,
        "analysis_summary": job.analysis_summary,
        "error_summary": job.error_summary,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "batches": [
            {
                "id": batch.id,
                "sequence_no": batch.sequence_no,
                "status": batch.status,
                "source_count": batch.source_count,
                "attempt_count": batch.attempt_count,
                "error_summary": batch.error_summary,
            }
            for batch in batches
        ],
    }


def process_next_voucher_preprocess_batch(db: Session, *, ai_client: VoucherPreprocessClient | None = None) -> bool:
    finalizing_job = db.scalars(
        select(VoucherAiPreprocessJob)
        .where(VoucherAiPreprocessJob.status == "FINALIZING")
        .order_by(VoucherAiPreprocessJob.created_at, VoucherAiPreprocessJob.id)
    ).first()
    if finalizing_job is not None:
        _finalize_completed_job(db, job_id=finalizing_job.id)
        return True

    batch_id = _claim_next_batch(db)
    if batch_id is None:
        return False

    batch = db.get(VoucherAiPreprocessBatch, batch_id)
    if batch is None:
        return False
    job = db.get(VoucherAiPreprocessJob, batch.job_id)
    if job is None:
        return False
    client = ai_client or _client_for_job(job.model)
    try:
        ai_response = client.propose_voucher_tasks(batch.payload)
        normalized = _normalize_ai_response(ai_response, payload_ref_index=_payload_ref_index(batch.payload))
    except VoucherAiPreprocessUnavailableError as exc:
        _handle_batch_failure(db, batch=batch, job=job, error_summary=str(exc))
        return True
    except Exception:
        _handle_batch_failure(db, batch=batch, job=job, error_summary="AI 服务暂时不可用")
        return True

    db.refresh(job)
    if job.status == "CANCELLED":
        batch.status = "CANCELLED"
        batch.completed_at = datetime.utcnow()
        db.commit()
        return True

    batch.status = "SUCCEEDED"
    batch.suggestions = normalized["task_suggestions"]
    batch.analysis_summary = normalized["analysis_summary"]
    batch.error_summary = ""
    batch.completed_at = datetime.utcnow()
    _refresh_job_counts(db, job)
    db.commit()
    _finalize_completed_job(db, job_id=job.id)
    return True


def _claim_next_batch(db: Session) -> UUID | None:
    now = datetime.utcnow()
    stale_before = now - timedelta(seconds=RUNNING_LEASE_SECONDS)
    stale_batches = list(
        db.scalars(
            select(VoucherAiPreprocessBatch).where(
                VoucherAiPreprocessBatch.status == "RUNNING",
                VoucherAiPreprocessBatch.started_at.is_not(None),
                VoucherAiPreprocessBatch.started_at < stale_before,
            )
        )
    )
    for stale_batch in stale_batches:
        stale_batch.status = "RETRY_WAIT"
        stale_batch.next_attempt_at = now
        stale_batch.error_summary = "Worker 中断，已自动恢复。"

    batch = db.scalars(
        select(VoucherAiPreprocessBatch)
        .join(VoucherAiPreprocessJob, VoucherAiPreprocessBatch.job_id == VoucherAiPreprocessJob.id)
        .where(
            VoucherAiPreprocessJob.status.in_({"QUEUED", "RUNNING"}),
            or_(
                VoucherAiPreprocessBatch.status == "QUEUED",
                and_(
                    VoucherAiPreprocessBatch.status == "RETRY_WAIT",
                    VoucherAiPreprocessBatch.next_attempt_at.is_not(None),
                    VoucherAiPreprocessBatch.next_attempt_at <= now,
                ),
            ),
        )
        .order_by(VoucherAiPreprocessBatch.created_at, VoucherAiPreprocessBatch.sequence_no)
        .with_for_update(skip_locked=True)
    ).first()
    if batch is None:
        if stale_batches:
            db.commit()
        return None

    job = db.get(VoucherAiPreprocessJob, batch.job_id)
    if job is None:
        return None
    batch.status = "RUNNING"
    batch.attempt_count += 1
    batch.next_attempt_at = None
    batch.error_summary = ""
    batch.started_at = now
    if job.status == "QUEUED":
        job.status = "RUNNING"
        job.started_at = job.started_at or now
    db.commit()
    return batch.id


def _handle_batch_failure(db: Session, *, batch: VoucherAiPreprocessBatch, job: VoucherAiPreprocessJob, error_summary: str) -> None:
    if error_summary == "AI 输出过长被截断，请缩小数据范围后重试" and _split_length_limited_batch(db, batch=batch, job=job):
        return

    max_attempts = max(1, get_settings().voucher_ai_max_attempts)
    if batch.attempt_count < max_attempts:
        retry_index = min(batch.attempt_count - 1, len(RETRY_DELAYS_MINUTES) - 1)
        batch.status = "RETRY_WAIT"
        batch.next_attempt_at = datetime.utcnow() + timedelta(minutes=RETRY_DELAYS_MINUTES[retry_index])
    else:
        batch.status = "FAILED"
        batch.completed_at = datetime.utcnow()
    batch.error_summary = error_summary
    _refresh_job_counts(db, job)
    db.commit()


def _split_length_limited_batch(db: Session, *, batch: VoucherAiPreprocessBatch, job: VoucherAiPreprocessJob) -> bool:
    max_sources = max(1, batch.source_count // 2)
    child_payloads = _build_batch_payloads(batch.payload, max_sources=max_sources)
    if len(child_payloads) <= 1:
        return False

    batch.status = "SPLIT"
    batch.completed_at = datetime.utcnow()
    batch.error_summary = "AI 输出过长，已自动拆分为更小批次。"
    next_sequence = max(
        db.scalars(
            select(VoucherAiPreprocessBatch.sequence_no).where(VoucherAiPreprocessBatch.job_id == job.id)
        ).all(),
        default=0,
    )
    for offset, child_payload in enumerate(child_payloads, start=1):
        db.add(
            VoucherAiPreprocessBatch(
                channel_id=DEFAULT_CHANNEL_ID,
                organization_id=job.organization_id,
                job_id=job.id,
                parent_batch_id=batch.id,
                sequence_no=next_sequence + offset,
                source_count=_source_count(child_payload),
                payload=child_payload,
            )
        )
    db.flush()
    _refresh_job_counts(db, job)
    db.commit()
    return True


def _finalize_completed_job(db: Session, *, job_id: UUID) -> None:
    job = db.get(VoucherAiPreprocessJob, job_id)
    if job is None or job.status != "FINALIZING":
        return
    package = db.get(MonthlyWorkPackage, job.monthly_work_package_id)
    enterprise = db.get(Enterprise, package.enterprise_id) if package else None
    if package is None or enterprise is None:
        _fail_finalization(db, job, "工作包或企业不存在，无法生成凭证。")
        return
    payload = build_voucher_preprocess_payload(db, package=package, enterprise=enterprise)
    if _payload_fingerprint(payload) != job.input_fingerprint:
        job.status = "STALE"
        job.error_summary = "预处理期间原始资料已变更，请重新发起 AI 预处理。"
        job.completed_at = datetime.utcnow()
        db.commit()
        return

    batches = list(
        db.scalars(
            select(VoucherAiPreprocessBatch)
            .where(VoucherAiPreprocessBatch.job_id == job.id, VoucherAiPreprocessBatch.status == "SUCCEEDED")
            .order_by(VoucherAiPreprocessBatch.sequence_no, VoucherAiPreprocessBatch.id)
        )
    )
    suggestions = [suggestion for batch in batches for suggestion in (batch.suggestions or [])]
    try:
        source_ref_index = _source_ref_index(db, package=package)
        created_match_result = _apply_ai_match_suggestions(
            db,
            package=package,
            suggestions=suggestions,
            source_ref_index=source_ref_index,
        )
        _retire_reassigned_single_source_vouchers(
            db,
            package=package,
            bank_transaction_ids=created_match_result["bank_transaction_ids"],
            invoice_ids=created_match_result["invoice_ids"],
        )
        generated = generate_voucher_drafts(db, monthly_work_package_id=package.id, commit=False)
        _attach_preprocess_metadata(
            generated["vouchers"],
            suggestions=suggestions,
            source_ref_index=source_ref_index,
            ai_status="SUCCESS",
        )
        analysis_summary = "；".join(batch.analysis_summary for batch in batches if batch.analysis_summary)[:500]
        started_at = job.started_at or job.created_at
        duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
        audit = _build_audit(
            started_at=time.monotonic(),
            payload=payload,
            model=job.model,
            used_kimi=True,
            ai_status="SUCCESS",
            created_vouchers=generated["created_vouchers"],
            generated_task_counts=_task_counts(generated["vouchers"]),
            error_summary="",
            analysis_summary=analysis_summary,
            suggestion_count=len(suggestions),
            created_match_records=len(created_match_result["match_ids"]),
        )
        audit["duration_ms"] = duration_ms
        _write_audit_log(db, package=package, audit=audit)
        job.status = "SUCCEEDED"
        job.created_vouchers = generated["created_vouchers"]
        job.analysis_summary = analysis_summary
        job.error_summary = ""
        job.completed_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        recovered_job = db.get(VoucherAiPreprocessJob, job_id)
        if recovered_job is not None:
            _fail_finalization(db, recovered_job, "生成凭证结果保存失败，请重试失败批次。")


def _fail_finalization(db: Session, job: VoucherAiPreprocessJob, error_summary: str) -> None:
    job.status = "PARTIAL_FAILED"
    job.error_summary = error_summary
    job.completed_at = datetime.utcnow()
    db.commit()


def _refresh_job_counts(db: Session, job: VoucherAiPreprocessJob) -> None:
    batches = list(db.scalars(select(VoucherAiPreprocessBatch).where(VoucherAiPreprocessBatch.job_id == job.id)))
    active_batches = [batch for batch in batches if batch.status != "SPLIT"]
    job.total_batches = len(active_batches)
    job.completed_batches = sum(1 for batch in active_batches if batch.status == "SUCCEEDED")
    job.failed_batches = sum(1 for batch in active_batches if batch.status == "FAILED")
    if job.status in {"QUEUED", "RUNNING"} and active_batches:
        if job.failed_batches and all(batch.status in {"SUCCEEDED", "FAILED"} for batch in active_batches):
            job.status = "PARTIAL_FAILED"
            job.completed_at = datetime.utcnow()
            job.error_summary = "部分 AI 预处理批次失败，可重试失败批次。"
        elif job.completed_batches == len(active_batches):
            job.status = "FINALIZING"
        elif any(batch.status == "RUNNING" for batch in active_batches):
            job.status = "RUNNING"


def _client_for_job(model: str) -> VoucherPreprocessClient:
    settings = get_settings()
    return MoonshotVoucherPreprocessClient(
        api_key=settings.moonshot_api_key,
        base_url=settings.moonshot_base_url,
        model=model,
        timeout_seconds=settings.moonshot_timeout_seconds,
    )


def _payload_fingerprint(payload: dict) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _build_batch_payloads(payload: dict, *, max_sources: int) -> list[dict]:
    max_sources = max(1, max_sources)
    rows_by_party: dict[tuple[str, str], list[tuple[str, dict]]] = {}
    for row in payload.get("bank_transactions", []):
        target_direction = "OUTPUT" if row.get("direction") == "RECEIPT" else "INPUT"
        rows_by_party.setdefault((str(row.get("counterparty_alias") or ""), target_direction), []).append(("bank", row))
    for row in payload.get("invoices", []):
        rows_by_party.setdefault((str(row.get("counterparty_alias") or ""), str(row.get("direction") or "")), []).append(
            ("invoice", row)
        )

    units: list[list[tuple[str, dict]]] = []
    for rows in rows_by_party.values():
        ordered_rows = sorted(rows, key=lambda item: (str(item[1].get("date") or ""), str(item[1].get("ref") or "")))
        units.extend(_split_rows(ordered_rows, max_sources=max_sources))

    batches: list[list[tuple[str, dict]]] = []
    current: list[tuple[str, dict]] = []
    for unit in sorted(units, key=lambda rows: (str(rows[0][1].get("date") or ""), str(rows[0][1].get("ref") or ""))):
        if current and len(current) + len(unit) > max_sources:
            batches.append(current)
            current = []
        current.extend(unit)
    if current:
        batches.append(current)
    return [_subset_payload(payload, batch_rows) for batch_rows in batches]


def _split_rows(rows: list[tuple[str, dict]], *, max_sources: int) -> list[list[tuple[str, dict]]]:
    return [rows[index : index + max_sources] for index in range(0, len(rows), max_sources)]


def _subset_payload(payload: dict, rows: list[tuple[str, dict]]) -> dict:
    bank_refs = {str(row["ref"]) for kind, row in rows if kind == "bank"}
    invoice_refs = {str(row["ref"]) for kind, row in rows if kind == "invoice"}
    bank_rows = [row for row in payload.get("bank_transactions", []) if str(row.get("ref")) in bank_refs]
    invoice_rows = [row for row in payload.get("invoices", []) if str(row.get("ref")) in invoice_refs]
    from app.services.voucher_ai_preprocess_service import _candidate_match_groups

    return {
        "package": payload.get("package") or {},
        "bank_transactions": bank_rows,
        "invoices": invoice_rows,
        "candidate_match_groups": _candidate_match_groups(bank_rows, invoice_rows),
        "matched_records": [
            item
            for item in payload.get("matched_records", [])
            if item.get("bank_ref") in bank_refs and item.get("invoice_ref") in invoice_refs
        ],
        "historical_rules": payload.get("historical_rules") or [],
    }


def _source_count(payload: dict) -> int:
    return len(payload.get("bank_transactions", [])) + len(payload.get("invoices", []))
