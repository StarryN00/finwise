from __future__ import annotations

import base64
from copy import deepcopy
from decimal import Decimal

import pytest

from app.ontology.contracts import ArtifactInput, FactInput, Scope, SourceAnchor
from app.ontology.enums import ObjectType
from app.ontology.errors import GatewayPaused, PreconditionFailed, ScopeViolation

from conftest import command


def build_demo(client, scope, variant="normal"):
    response = client.post("/api/v1/demo/procurement", json={"scope": scope, "variant": variant})
    assert response.status_code == 200, response.text
    return response.json()


def test_t00_health_and_idempotent_migration(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert client.get("/api/v1/ontology/contract").json()["object_scope_required"] is True


def test_demo_replay_does_not_duplicate_facts_or_block_the_group(client, scope):
    first = build_demo(client, scope)
    second = build_demo(client, scope)
    assert first["group"]["object_id"] == second["group"]["object_id"]
    overview = client.post("/api/v1/workbench", json={"scope": scope}).json()
    assert overview["counts"]["facts"] == 4
    assert overview["groups"][0]["data"]["reconciliation_status"] == "PASS"


def test_legacy_procurement_route_is_backed_by_idempotent_command(client, scope):
    demo = build_demo(client, scope)
    response = client.post("/api/v1/business/procurement", json={
        "scope": scope, "fact_ids": [item["object_id"] for item in demo["facts"]],
        "business_identity": "compat-command-group", "idempotency_key": "compat-command-001",
    })
    assert response.status_code == 200, response.text
    assert response.json()["effect"]["object"]["object_type"] == "ProcessingGroup"
    assert client.app.state.store.find_command("compat-command-001")["action"] == "create_procurement_group"
    duplicate = client.post("/api/v1/business/procurement", json={
        "scope": scope, "fact_ids": [item["object_id"] for item in demo["facts"]],
        "business_identity": "compat-command-group", "idempotency_key": "compat-command-001",
    })
    assert duplicate.status_code == 200 and duplicate.json()["idempotent"] is True


def test_auth_required_in_default_runtime(tmp_path):
    from pathlib import Path

    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    settings = Settings(root=Path(__file__).resolve().parents[1], database_path=tmp_path / "auth.db", storage_path=tmp_path / "artifacts", require_auth=True)
    secured = TestClient(create_app(settings))
    scope = {"tenant_id": "t", "organization_id": "o", "legal_entity_id": "l", "ledger_id": "g", "accounting_period_id": "2026-03", "baseline_id": "b"}
    assert secured.post("/api/v1/scopes", json=scope).status_code == 401


def test_same_period_isolated_across_scopes(client, scope):
    second_scope = {**scope, "organization_id": "org-b", "legal_entity_id": "legal-b", "ledger_id": "ledger-b", "baseline_id": "baseline-b-2026-03"}

    first = client.post("/api/v1/scopes", json=scope)
    second = client.post("/api/v1/scopes", json=second_scope)

    assert first.status_code == 200
    assert second.status_code == 200
    first_period = client.post("/api/v1/workbench", json={"scope": scope}).json()["period"]
    second_period = client.post("/api/v1/workbench", json={"scope": second_scope}).json()["period"]
    assert first_period["data"]["period"] == "2026-03"
    assert second_period["data"]["period"] == "2026-03"
    assert first_period["object_id"] != second_period["object_id"]


def test_workbench_progress_is_server_derived_from_actual_stage_state(client, scope):
    service = client.app.state.service
    typed = Scope(**scope)
    service.create_scope(typed, actor_id="fixture")
    empty = client.post("/api/v1/workbench", json={"scope": scope}).json()
    assert empty["progress"]["overall_percent"] == 0
    assert empty["progress"]["completed_count"] == 0
    assert empty["progress"]["current_stage"] == "source"
    assert [item["name"] for item in empty["progress"]["stages"]] == ["资料接收", "资料分析", "待确认与校验", "凭证复核", "交付归档"]

    populated = client.post("/api/v1/demo/procurement", json={"scope": scope, "variant": "normal"})
    assert populated.status_code == 200, populated.text
    overview = client.post("/api/v1/workbench", json={"scope": scope}).json()
    assert overview["progress"]["overall_percent"] > 0
    assert overview["progress"]["stages"][0]["status"] == "COMPLETED"
    assert overview["progress"]["overall_percent"] == round(overview["progress"]["completed_count"] / 5 * 100)


def test_full_procurement_vertical_slice_and_delivery(client, scope):
    demo = build_demo(client, scope)
    group = demo["group"]
    assert group["status"] == "CANDIDATE"
    assert group["data"]["evidence_grade"] == "A"
    assert all(item["result"] == "PASS" for item in demo["checks"])

    response = command(client, scope, "confirm_grouping", group["object_id"], group["version"], "group-confirm-001")
    assert response.status_code == 200, response.text
    group = response.json()["effect"]["object"]
    response = command(client, scope, "reconcile_group", group["object_id"], group["version"], "reconcile-001")
    assert response.status_code == 200, response.text
    group = client.post("/api/v1/workbench", json={"scope": scope}).json()["groups"][0]
    assert group["status"] == "READY"

    evidence = group["data"]["evidence_ids"]
    suggestion = client.post("/api/v1/agent/rule-suggestion", headers={"X-Actor-Id": "agent-test", "X-Role": "operator"}, json={"scope": scope, "group_id": group["object_id"], "model_version": "fixture-model-v1", "model_output": {"status": "PROPOSED", "summary": "采购货物候选规则", "confidence": 0.96, "items": [{"debit_account": "库存商品", "tax_account": "应交税费-进项税额", "credit_account": "银行存款"}], "evidence": evidence, "risk_level": "LOW", "next_action": "请人工确认"}})
    assert suggestion.status_code == 200, suggestion.text
    card = suggestion.json()["confirmation_card"]
    response = command(client, scope, "approve_rule", card["object_id"], card["version"], "rule-approve-001")
    assert response.status_code == 200, response.text
    assert response.json()["effect"]["rule_instance"]["status"] == "ACTIVE"
    assert client.post("/api/v1/workbench", json={"scope": scope}).json()["counts"]["pending_confirmation_cards"] == 0

    group = client.post("/api/v1/workbench", json={"scope": scope}).json()["groups"][0]
    response = command(client, scope, "generate_draft", group["object_id"], group["version"], "draft-001")
    assert response.status_code == 200, response.text
    voucher = response.json()["effect"]["object"]
    assert sum(Decimal(item["amount"]) for item in voucher["data"]["lines"] if item["direction"] == "DEBIT") == 1130
    assert voucher["data"]["formal_balance_impact"] is False
    response = command(client, scope, "validate_draft", voucher["object_id"], voucher["version"], "validate-001", role="reviewer")
    assert response.status_code == 200, response.text
    voucher = response.json()["effect"]["object"]

    group = client.post("/api/v1/workbench", json={"scope": scope}).json()["groups"][0]
    package_response = command(client, scope, "release_delivery", group["object_id"], group["version"], "release-001", role="reviewer")
    assert package_response.status_code == 200, package_response.text
    package = package_response.json()["effect"]["object"]
    export_response = command(client, scope, "export_package", package["object_id"], package["version"], "export-001", role="reviewer")
    assert export_response.status_code == 200, export_response.text
    package = export_response.json()["effect"]["package"]
    receipt_payload = {"status": "IMPORTED", "external_batch": "ERP-001", "export_id": package["data"]["export_id"], "voucher_version_id": package["data"]["voucher_version_id"], "voucher_version": package["data"]["voucher_version"]}
    ack_response = command(client, scope, "ack_external_import", package["object_id"], package["version"], "ack-0001", receipt_payload, role="reviewer")
    assert ack_response.status_code == 200, ack_response.text
    imported_package = ack_response.json()["effect"]["package"]
    duplicate_ack = command(client, scope, "ack_external_import", imported_package["object_id"], imported_package["version"], "ack-0002", receipt_payload, role="reviewer")
    assert duplicate_ack.status_code == 200, duplicate_ack.text
    assert duplicate_ack.json()["effect"]["deduplicated"] is True

    period = client.post("/api/v1/workbench", json={"scope": scope}).json()["period"]
    closed = command(client, scope, "close_period", period["object_id"], period["version"], "close-001")
    assert closed.status_code == 200, closed.text
    period = closed.json()["effect"]["object"]
    archived = command(client, scope, "archive_period", period["object_id"], period["version"], "archive-001")
    assert archived.status_code == 200, archived.text
    period = archived.json()["effect"]["object"]
    locked = command(client, scope, "lock_period", period["object_id"], period["version"], "lock-001", role="admin")
    assert locked.status_code == 200, locked.text
    assert locked.json()["effect"]["object"]["status"] == "LOCKED"

    content = base64.b64encode(b"late-write").decode()
    blocked_write = client.post("/api/v1/artifacts", json={"scope": scope, "filename": "late.txt", "content_base64": content})
    assert blocked_write.status_code == 409


def test_scope_isolation_version_conflict_and_command_idempotency(client, scope):
    demo = build_demo(client, scope)
    group = demo["group"]
    wrong_scope = {**scope, "legal_entity_id": "legal-b"}
    detail = client.post("/api/v1/objects/detail", json={"scope": wrong_scope, "object_id": group["object_id"]})
    assert detail.status_code == 403
    stale = command(client, scope, "confirm_grouping", group["object_id"], group["version"] - 1, "stale-group-001")
    assert stale.status_code == 409
    ok = command(client, scope, "confirm_grouping", group["object_id"], group["version"], "same-key-001")
    assert ok.status_code == 200
    duplicate = command(client, scope, "confirm_grouping", group["object_id"], group["version"], "same-key-001")
    assert duplicate.status_code == 200
    assert duplicate.json()["idempotent"] is True


def test_missing_evidence_only_blocks_affected_group(client, scope):
    demo = build_demo(client, scope, "missing_stock")
    group = demo["group"]
    assert "STOCK_IN" in group["data"]["missing_evidence"]
    assert command(client, scope, "confirm_grouping", group["object_id"], group["version"], "missing-confirm-001").status_code == 409
    overview = client.post("/api/v1/workbench", json={"scope": scope}).json()
    assert overview["counts"]["blockers"] == 1
    assert overview["deliverable_groups"] == []
    answer = client.post("/api/v1/query", json={"scope": scope, "question": "哪些业务组缺少入库证据？"})
    assert answer.status_code == 200
    assert answer.json()["result_count"] == 1
    assert "不等同于现实中没有入库" in answer.json()["explanation"]


def test_amount_mismatch_deterministic_block(client, scope):
    demo = build_demo(client, scope, "amount_mismatch")
    assert any(item["check_type"] == "PAYMENT_INVOICE" and item["result"] == "BLOCKED" for item in demo["checks"])
    group = demo["group"]
    assert group["status"] == "BLOCKED"
    assert command(client, scope, "confirm_grouping", group["object_id"], group["version"], "mismatch-confirm-001").status_code == 409


def test_gateway_pauses_unavailable_and_invalid_model_output(client, scope):
    demo = build_demo(client, scope)
    group = demo["group"]
    unavailable = client.post("/api/v1/agent/rule-suggestion", json={"scope": scope, "group_id": group["object_id"]})
    assert unavailable.status_code == 422
    assert "伪造结果" in unavailable.json()["error"]["message"]
    invalid = client.post("/api/v1/agent/rule-suggestion", json={"scope": scope, "group_id": group["object_id"], "model_output": {"status": "PROPOSED", "summary": "缺证据", "confidence": 1.2, "items": [], "evidence": [], "risk_level": "HIGH", "next_action": "暂停"}})
    assert invalid.status_code == 422
    runs = client.post("/api/v1/workbench", json={"scope": scope}).json()["history_runs"]
    assert runs[-1]["status"] == "PAUSED"


def test_duplicate_upload_preserves_original_bytes(client, scope):
    client.post("/api/v1/scopes", json=scope)
    body = {"scope": scope, "filename": "invoice.txt", "content_base64": base64.b64encode(b"immutable").decode(), "mime_type": "text/plain"}
    first = client.post("/api/v1/artifacts", json=body).json()
    second = client.post("/api/v1/artifacts", json={**body, "filename": "renamed.txt"}).json()
    assert first["object_id"] == second["object_id"]
    content = client.get("/api/v1/artifacts/%s/content" % first["object_id"], params=scope)
    assert content.status_code == 200
    assert content.content == b"immutable"


def test_period_mismatch_is_retained_but_cannot_be_processed(client, scope):
    client.post("/api/v1/scopes", json=scope)
    body = {"scope": scope, "filename": "future.txt", "content_base64": base64.b64encode(b"future").decode(), "observed_period": "2026-04"}
    artifact = client.post("/api/v1/artifacts", json=body).json()
    assert artifact["status"] == "PERIOD_EXCEPTION"
    fact = client.post("/api/v1/facts", json={"scope": scope, "source_artifact_id": artifact["object_id"], "source_anchor": {"page": 1}, "record_type": "INVOICE", "original_value": {}, "normalized_value": {}, "parser_version": "v1", "extraction_confidence": .9})
    assert fact.status_code == 409


def test_fact_requires_anchor_and_reparse_creates_version(client, scope):
    app = client.app
    service = app.state.service
    typed_scope = Scope.model_validate(scope)
    service.create_scope(typed_scope)
    artifact = service.create_artifact(ArtifactInput(scope=typed_scope, filename="a.txt", content_base64=base64.b64encode(b"a").decode()), actor_id="alice")
    try:
        service.create_fact_record(FactInput(scope=typed_scope, source_artifact_id=artifact["object_id"], source_anchor=SourceAnchor(), record_type="INVOICE", original_value={}, normalized_value={}, parser_version="v1", extraction_confidence=.9), actor_id="alice")
    except PreconditionFailed:
        pass
    else:
        raise AssertionError("missing source anchor must fail")
    fact = service.create_fact_record(FactInput(scope=typed_scope, source_artifact_id=artifact["object_id"], source_anchor=SourceAnchor(page=1), record_type="INVOICE", original_value={"total": 10}, normalized_value={"invoice_total": 10}, parser_version="v1", extraction_confidence=.9), actor_id="alice")
    revised = service.reparse_fact(typed_scope, fact_id=fact["object_id"], actor_id="alice", expected_version=1, parser_version="v2", normalized_value={"invoice_total": 11})
    assert revised["version"] == 2
    assert service.store.get_object(fact["object_id"], typed_scope, 1)["data"]["normalized_value"]["invoice_total"] == 10


def test_run_retry_replay_and_late_result_is_rejected(client, scope):
    demo = build_demo(client, scope)
    service = client.app.state.service
    typed_scope = Scope.model_validate(scope)
    run = service.create_run(typed_scope, actor_id="alice", input_ids=[item["object_id"] for item in demo["facts"]])
    service.cancel_run(typed_scope, run_id=run["run_id"], actor_id="alice")
    try:
        service.complete_run(typed_scope, run_id=run["run_id"], actor_id="worker", result={"late": True})
    except PreconditionFailed:
        pass
    else:
        raise AssertionError("cancelled Run must reject late result")
    retry = service.retry_run(typed_scope, run_id=run["run_id"], actor_id="alice")
    assert retry["attempt"] == 2
    replay = service.replay_run(typed_scope, run_id=retry["run_id"], actor_id="alice")
    assert replay["parent_run_id"] == retry["run_id"]
    assert service.store.get_run(run["run_id"], typed_scope)["status"] == "CANCELLED"


def test_agent_cannot_promote_rule_without_human_command(client, scope):
    demo = build_demo(client, scope)
    service = client.app.state.service
    typed_scope = Scope.model_validate(scope)
    group = demo["group"]
    result = service.agent_suggest_rule(typed_scope, group_id=group["object_id"], actor_id="agent", model_output={"status": "PROPOSED", "summary": "候选", "confidence": .95, "items": [{"debit_account": "办公费"}], "evidence": group["data"]["evidence_ids"], "risk_level": "LOW", "next_action": "人工确认"})
    assert result["candidate"]["status"] == "PROPOSED"
    assert service.store.list_objects(ObjectType.RULE_INSTANCE.value, typed_scope) == []


def test_contract_rejects_unknown_relation_and_generic_agents_remain_candidates(client, scope):
    demo = build_demo(client, scope)
    service = client.app.state.service
    typed_scope = Scope.model_validate(scope)
    group = demo["group"]
    evidence = group["data"]["evidence_ids"]
    output = {"status": "PROPOSED", "summary": "候选业务事件", "confidence": .8, "items": [{"stable_identity": "candidate-001"}], "evidence": evidence, "risk_level": "MEDIUM", "next_action": "人工确认"}
    result = service.agent_suggest(typed_scope, stage="BUSINESS_EVENT", actor_id="agent", model_output=output)
    assert result["candidate"]["status"] == "CANDIDATE"
    assert service.store.list_objects(ObjectType.RULE_INSTANCE.value, typed_scope) == []
    try:
        service.store.add_relation("UNDECLARED", group, group)
    except ValueError:
        pass
    else:
        raise AssertionError("undeclared relation must be rejected")


def test_rule_conflict_creates_confirmation_block(client, scope):
    demo = build_demo(client, scope)
    service = client.app.state.service
    typed_scope = Scope.model_validate(scope)
    group = demo["group"]
    suggestion = service.agent_suggest_rule(typed_scope, group_id=group["object_id"], actor_id="agent", model_output={"status": "PROPOSED", "summary": "疑似设备采购", "confidence": .9, "items": [{"debit_account": "固定资产"}], "evidence": group["data"]["evidence_ids"], "risk_level": "HIGH", "next_action": "人工确认"})
    card = suggestion["confirmation_card"]
    response = command(client, scope, "approve_rule", card["object_id"], card["version"], "rule-conflict-001", {"conflict": True, "historical_rule": "办公费", "reason": "本期描述疑似设备采购"})
    assert response.status_code == 409
    conflicts = service.store.list_objects(ObjectType.RULE_CONFLICT.value, typed_scope)
    assert len(conflicts) == 1 and conflicts[0]["status"] == "OPEN"
    assert command(client, scope, "approve_rule", card["object_id"], card["version"], "bypass-rule-conflict").status_code == 409


def test_rule_conflict_can_be_resolved_then_rule_can_be_revoked(client, scope):
    demo = build_demo(client, scope)
    service = client.app.state.service
    typed_scope = Scope.model_validate(scope)
    suggestion = service.agent_suggest_rule(typed_scope, group_id=demo["group"]["object_id"], actor_id="agent", model_output={
        "status": "PROPOSED", "summary": "疑似设备采购", "confidence": .9,
        "items": [{"debit_account": "固定资产"}], "evidence": demo["group"]["data"]["evidence_ids"],
        "risk_level": "HIGH", "next_action": "人工确认"})
    card = suggestion["confirmation_card"]
    rejected = command(client, scope, "approve_rule", card["object_id"], card["version"], "make-rule-conflict", {
        "conflict": True, "historical_rule": "办公费", "reason": "本期描述疑似设备采购"})
    assert rejected.status_code == 409
    conflict = service.store.list_objects(ObjectType.RULE_CONFLICT.value, typed_scope)[0]
    resolved = command(client, scope, "resolve_rule_conflict", conflict["object_id"], conflict["version"], "resolve-rule-conflict", {
        "resolution": "ACCEPT_CANDIDATE", "reason": "人工复核后接受本期候选规则"})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["effect"]["conflict"]["status"] == "RESOLVED"
    approved = command(client, scope, "approve_rule", card["object_id"], card["version"], "approve-after-conflict")
    assert approved.status_code == 200, approved.text
    rule = approved.json()["effect"]["rule_instance"]
    revoked = command(client, scope, "revoke_rule", rule["object_id"], rule["version"], "revoke-rule", {"reason": "规则已被会计政策替代"})
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["effect"]["rule"]["status"] == "REVOKED"
    assert service._find_rule_for_group(typed_scope, demo["group"]["object_id"]) is None


def test_confirmed_baseline_keeps_a_reusable_prior_close_snapshot(client, scope):
    build_demo(client, scope)
    service = client.app.state.service
    typed_scope = Scope.model_validate(scope)
    baseline = service.workbench(typed_scope)["baseline"]
    snapshot = baseline["data"]["prior_close_snapshot"]
    assert snapshot["period"] == "2026-02"
    assert snapshot["lines"] and snapshot["snapshot_digest"]
    service._require_baseline_confirmed(typed_scope)
    tampered = deepcopy(baseline["data"])
    tampered["prior_close_snapshot"]["lines"][0]["closing_debit"] = "999.00"
    service.store.revise_object(baseline["object_id"], baseline["version"], typed_scope, tampered, status="CONFIRMED", created_by="fixture")
    with pytest.raises(PreconditionFailed, match="快照"):
        service._require_baseline_confirmed(typed_scope)


def test_group_split_and_merge_retains_lineage_and_removes_old_primary_groups(client, scope):
    demo = build_demo(client, scope)
    service = client.app.state.service
    typed_scope = Scope.model_validate(scope)
    original = demo["group"]
    split_fact = original["data"]["member_fact_ids"][0]
    new_group = service.split_group(typed_scope, group_id=original["object_id"], expected_version=original["version"],
                                   fact_ids=[split_fact], actor_id="alice")
    revised_original = service.store.get_object(original["object_id"], typed_scope)
    assert revised_original["status"] == "REVISED"
    assert new_group["data"]["lineage"][0]["type"] == "SPLIT_FROM"
    merged = service.merge_groups(typed_scope, group_ids=[revised_original["object_id"], new_group["object_id"]], actor_id="alice")
    assert merged["data"]["lineage"]
    assert service.store.get_object(revised_original["object_id"], typed_scope)["status"] == "MERGED"
    assert service.store.get_object(new_group["object_id"], typed_scope)["status"] == "MERGED"
    assert set(merged["data"]["member_fact_ids"]) == set(original["data"]["member_fact_ids"])


def test_agent_input_is_whitelisted_and_sensitive_fields_do_not_cross_gateway(client, scope):
    demo = build_demo(client, scope)
    service = client.app.state.service
    typed_scope = Scope.model_validate(scope)
    group = demo["group"]
    fact = service.store.get_object(group["data"]["member_fact_ids"][0], typed_scope)
    changed = dict(fact["data"])
    changed["normalized_value"] = {"invoice_total": 10, "enterprise_name": "不应发送", "tax_id": "secret-tax-id"}
    service.store.revise_object(fact["object_id"], fact["version"], typed_scope, changed, status="PARSED", created_by="test")
    result = service.agent_suggest_rule(typed_scope, group_id=group["object_id"], actor_id="agent", model_output={"status": "PROPOSED", "summary": "候选", "confidence": .95, "items": [{"debit_account": "办公费"}], "evidence": group["data"]["evidence_ids"], "risk_level": "LOW", "next_action": "人工确认"})
    serialized = str(result["model_run"]["data"]["input_summary"])
    assert "不应发送" not in serialized and "secret-tax-id" not in serialized
    assert "invoice_total" in serialized
