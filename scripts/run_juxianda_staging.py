"""Persisted Staging run for the real Juxianda 2026-03 source set.

This runner deliberately keeps the external source directory read-only. It
copies source bytes into an isolated SQLite/artifact directory, runs the local
deterministic parser, calls the server-owned DeepSeek Gateway once, and never
approves a rule, creates a voucher, exports, or writes to an external system.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import create_user, grant_scope
from app.config import Settings
from app.main import create_app
from app.ontology.contracts import ArtifactInput, Scope
from app.ontology.enums import ObjectType, RelationType
from app.ontology.errors import DomainError
from app.ontology.service import OntologyService

from run_juxianda_ingestion import DEFAULT_ROOT, SUPPORTED, observed_period


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = PROJECT_ROOT / "data" / "staging-juxianda-2026-03"
ACTOR_ID = "juxianda-staging-operator"
DEFAULT_USER = "juxianda-staging"
DEFAULT_PASSWORD = "FinWiseJuxianda!2026"
SCOPE = Scope(
    tenant_id="juxianda-test",
    organization_id="kunshan-juxianda",
    legal_entity_id="kunshan-juxianda",
    ledger_id="chengyuan-ledger",
    accounting_period_id="2026-03",
    baseline_id="baseline-2026-03",
)


def ensure_user(settings: Settings, scope: Scope) -> str:
    user_id = os.getenv("FINWISE_STAGING_USER", DEFAULT_USER)
    password = os.getenv("FINWISE_STAGING_PASSWORD", DEFAULT_PASSWORD)
    with settings_database(settings).connect() as connection:
        exists = connection.execute("SELECT 1 FROM auth_users WHERE user_id=?", (user_id,)).fetchone()
    if not exists:
        create_user(settings_database(settings), user_id, password, "accountant")
    grant_scope(settings_database(settings), user_id, scope)
    return user_id


def settings_database(settings: Settings):
    from app.db import Database
    return Database(settings)


def ensure_fact_evidence(service: OntologyService, scope: Scope, fact_ids: list[str]) -> list[str]:
    evidence_ids = []
    for fact_id in fact_ids:
        evidence = service._find_evidence_for_fact(scope, fact_id)
        if evidence is None:
            fact = service.store.get_object(fact_id, scope)
            evidence = service.store.create_initial_object(
                ObjectType.EVIDENCE.value,
                scope,
                {
                    "fact_record_id": fact["object_id"],
                    "fact_version": fact["version"],
                    "source_artifact_id": fact["data"]["source_artifact_id"],
                    "source_anchor": fact["data"].get("source_anchor"),
                    "claim_type": "FACT_SUPPORT",
                    "grade": "D",
                    "complete": False,
                    "independent": False,
                    "expired": False,
                    "conflict": False,
                    "human_confirmed": False,
                    "staging_note": "仅用于真实模型建议链路验收，不代表采购证据完整",
                },
                status="VALID",
                created_by=ACTOR_ID,
            )
            service.store.add_relation(RelationType.SUPPORTS.value, evidence, fact, evidence=[fact_id], created_by=ACTOR_ID, status="PROPOSED")
        evidence_ids.append(evidence["object_id"])
    return evidence_ids


def run(source_root: Path, data_root: Path) -> dict:
    if not source_root.is_dir():
        raise SystemExit(f"资料目录不存在：{source_root}")
    data_root.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        root=PROJECT_ROOT,
        database_path=data_root / "finwise.db",
        storage_path=data_root / "artifacts",
        require_auth=True,
        environment="staging",
        agent_mode=os.getenv("FINWISE_AGENT_MODE", "gateway"),
        agent_provider=os.getenv("FINWISE_AGENT_PROVIDER", "deepseek"),
        agent_model=os.getenv("FINWISE_AGENT_MODEL", "deepseek-chat"),
        deepseek_base_url=os.getenv("FINWISE_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_api_key=os.getenv("FINWISE_DEEPSEEK_API_KEY", ""),
        agent_prompt_version=os.getenv("FINWISE_AGENT_PROMPT_VERSION", "finwise-agent-prompt-v1"),
        agent_max_tokens=int(os.getenv("FINWISE_AGENT_MAX_TOKENS", "1200")),
        gateway_timeout_seconds=float(os.getenv("FINWISE_GATEWAY_TIMEOUT_SECONDS", "45")),
        gateway_max_retries=int(os.getenv("FINWISE_GATEWAY_MAX_RETRIES", "0")),
    )
    settings.validate_runtime()
    app = create_app(settings)
    service: OntologyService = app.state.service
    service.create_scope(SCOPE, actor_id=ACTOR_ID)
    user_id = ensure_user(settings, SCOPE)

    files = []
    for source in sorted(source_root.iterdir()):
        artifact = service.create_artifact(
            ArtifactInput(
                scope=SCOPE,
                filename=source.name,
                content_base64=base64.b64encode(source.read_bytes()).decode(),
                observed_period=observed_period(source.name),
            ),
            actor_id=ACTOR_ID,
        )
        kind = SUPPORTED.get(source.name)
        item = {
            "file": source.name,
            "artifact": artifact["object_id"],
            "artifact_status": artifact["status"],
            "observed_period": observed_period(source.name),
            "kind": kind or "RECEIVED_ONLY",
        }
        if kind and item["observed_period"] not in {"UNKNOWN", SCOPE.accounting_period_id}:
            item.update({"parse_status": "SKIPPED_PERIOD_EXCEPTION", "counts": {"rows": 0, "parsed": 0, "needs_review": 0, "period_exception": 0}, "errors": ["原件期间与当前工作期间不一致，按门禁保留待处理"]})
        elif kind:
            effect = service.execute_command(
                SCOPE,
                action="parse_artifact",
                target_id=artifact["object_id"],
                target_version=artifact["version"],
                idempotency_key="juxianda-staging-parse-" + artifact["object_id"],
                actor_id=ACTOR_ID,
                role="accountant",
                payload={"document_kind": kind, **({"bank_account_ref": "juxianda-bank-" + source.stem} if kind == "bank_statement" else {})},
            )["effect"]
            item.update({"parse_status": effect["artifact"]["data"].get("parse_status"), "counts": effect["counts"], "errors": effect["errors"], "sheets": effect["sheets"]})
        files.append(item)

    facts = service.store.list_objects(ObjectType.FACT_RECORD.value, SCOPE)
    invoices = [item for item in facts if item["data"].get("record_type") == "INVOICE"]
    payments = [item for item in facts if item["data"].get("record_type") == "PAYMENT"]
    ready_payments = [item for item in payments if item["status"] == "PARSED"]
    group = next((item for item in service.store.list_objects(ObjectType.PROCESSING_GROUP.value, SCOPE) if item["data"].get("business_identity") == "juxianda-real-source-ai-check-001"), None)
    if group is None and len(ready_payments) >= 2:
        selected_ids = [item["object_id"] for item in ready_payments[:2]]
        ensure_fact_evidence(service, SCOPE, selected_ids)
        group = service.create_procurement_business(SCOPE, fact_ids=selected_ids, business_identity="juxianda-real-source-ai-check-001", actor_id=ACTOR_ID)
    elif group is not None:
        selected_ids = group["data"].get("member_fact_ids", [])
        ensure_fact_evidence(service, SCOPE, selected_ids)
    else:
        selected_ids = []

    procurement_gate = {
        "status": "BLOCKED",
        "invoice_candidates": len(invoices),
        "invoice_ready": len([item for item in invoices if item["status"] == "PARSED"]),
        "payment_candidates": len(payments),
        "payment_ready": len(ready_payments),
        "missing_evidence": ["CONTRACT", "STOCK_IN"],
        "reason": "聚贤达当前资料存在缺合同、入库证据及发票待复核；本轮不生成正式凭证或交付包",
    }
    agent_result = {"status": "NOT_RUN", "reason": "没有足够的已解析付款事实建立受控候选组"}
    reconciliation = []
    if group is not None:
        group = service.store.get_object(group["object_id"], SCOPE)
        try:
            reconciliation = service.reconcile_group(SCOPE, group_id=group["object_id"], actor_id=ACTOR_ID)
        except DomainError as exc:
            procurement_gate["reason"] = str(exc)
        try:
            existing_runs = [item for item in service.store.list_objects(ObjectType.MODEL_RUN.value, SCOPE) if item["data"].get("stage") == "RULE_SUGGESTION" and item["status"] == "SUCCEEDED"]
            if existing_runs:
                agent_result = {"status": "ALREADY_RECORDED", "model_run_id": existing_runs[-1]["object_id"], "mock": existing_runs[-1]["data"].get("gateway", {}).get("mock")}
            else:
                result = service.agent_suggest_rule(SCOPE, group_id=group["object_id"], actor_id=ACTOR_ID, model_output=None, model_version=settings.agent_model)
                agent_result = {"status": "SUCCEEDED", "model_run_id": result["model_run"]["object_id"], "suggestion_id": result["suggestion"]["object_id"], "candidate_id": result["candidate"]["object_id"], "mock": result["model_run"]["data"].get("gateway", {}).get("mock"), "model": result["model_run"]["data"].get("model_version"), "gateway": result["model_run"]["data"].get("gateway", {})}
        except DomainError as exc:
            agent_result = {"status": "PAUSED", "reason": str(exc), "mock": False}

    report = {
        "run_type": "juxianda-staging-real-agent",
        "scope": SCOPE.model_dump(),
        "database": str(settings.database_path),
        "artifact_root": str(settings.storage_path),
        "authorized_user": user_id,
        "source_root": str(source_root),
        "files": files,
        "artifact_count": len(service.store.list_objects(ObjectType.SOURCE_ARTIFACT.value, SCOPE)),
        "fact_count": len(facts),
        "procurement_gate": procurement_gate,
        "candidate_group_id": group["object_id"] if group else None,
        "candidate_fact_ids": selected_ids,
        "reconciliation": reconciliation,
        "agent": agent_result,
        "formal_voucher_created": bool(service.store.list_objects(ObjectType.VOUCHER_VERSION.value, SCOPE)),
        "external_write_performed": False,
    }
    report_path = data_root / "staging-run-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="持久化执行聚贤达 2026-03 Staging 真实 Gateway 验收")
    parser.add_argument("source_root", nargs="?", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    args = parser.parse_args()
    print(json.dumps(run(args.source_root, args.data_root), ensure_ascii=False, indent=2, default=str))
