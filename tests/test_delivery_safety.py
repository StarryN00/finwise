import pytest

from app.ontology.contracts import Scope
from app.ontology.enums import ObjectType
from conftest import command
from test_system import build_demo


def ready_voucher(client, scope):
    demo = build_demo(client, scope)
    service = client.app.state.service
    typed = Scope(**scope)
    group = demo["group"]
    group = service.confirm_grouping(typed, group_id=group["object_id"], actor_id="alice", expected_version=group["version"])
    service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    result = service.agent_suggest_rule(typed, group_id=group["object_id"], actor_id="alice", model_output={
        "summary": "fixture", "status": "PROPOSED", "confidence": .9,
        "items": [{"debit_account": "库存商品", "credit_account": "银行存款"}],
        "evidence": group["data"]["evidence_ids"], "risk_level": "LOW", "next_action": "人工确认"})
    card = result["confirmation_card"]
    service.approve_rule(typed, card_id=card["object_id"], actor_id="alice", expected_version=card["version"])
    voucher = service.generate_draft(typed, group_id=group["object_id"], actor_id="alice")
    return service, typed, group, voucher


def exported_package(client, scope):
    service, typed, group, voucher = ready_voucher(client, scope)
    voucher = service.validate_draft(typed, voucher_id=voucher["object_id"], actor_id="reviewer", expected_version=voucher["version"])
    package = service.release_delivery(typed, group_id=group["object_id"], actor_id="reviewer")
    exported = service.export_package(typed, package_id=package["object_id"], actor_id="reviewer")
    return service, typed, group, voucher, exported


def receipt_for(package, status="IMPORTED"):
    return {"status": status, "external_batch": "ERP-test", "export_id": package["data"]["export_id"],
            "voucher_version_id": package["data"]["voucher_version_id"], "voucher_version": package["data"]["voucher_version"]}


def test_failed_receipt_cannot_complete_or_close_period(client, scope):
    service, typed, group, voucher, exported = exported_package(client, scope)
    p = exported["package"]
    receipt = {**receipt_for(p, "FAILED"), "reason": "外部科目不存在"}
    response = command(client, scope, "ack_external_import", p["object_id"], p["version"], "failed-receipt-001", receipt)
    assert response.status_code == 200, response.text
    p = response.json()["effect"]["package"]
    assert p["status"] == "EXPORT_CREATED"
    assert "external_imported_at" not in p["data"]
    period = service.workbench(typed)["period"]
    assert command(client, scope, "close_period", period["object_id"], period["version"], "close-failed-receipt").status_code == 409
    duplicate = command(client, scope, "ack_external_import", p["object_id"], p["version"], "failed-receipt-002", receipt)
    assert duplicate.json()["effect"]["deduplicated"] is True


def test_history_returns_prior_scopes_and_only_external_archived_vouchers(client, scope):
    service, typed, group, voucher, exported = exported_package(client, scope)
    package = service.ack_external_import(typed, package_id=exported["package"]["object_id"], actor_id="alice", payload=receipt_for(exported["package"]))["package"]
    response = client.post("/api/v1/history", json={"scope": scope})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["periods"]) == 1
    assert len(body["archived_vouchers"]) == 1
    assert body["archived_vouchers"][0]["package"]["object_id"] == package["object_id"]
    assert body["archived_vouchers"][0]["export"]["data"]["voucher_version"] == voucher["version"]


@pytest.mark.parametrize("payload", [{}, {"status": "BOGUS", "external_batch": "x"}, {"status": "IMPORTED"}])
def test_receipt_requires_explicit_valid_outcome_and_batch(client, scope, payload):
    _, _, _, _, exported = exported_package(client, scope)
    p = exported["package"]
    assert command(client, scope, "ack_external_import", p["object_id"], p["version"], "invalid-receipt-test", payload).status_code == 409


@pytest.mark.parametrize("lines", [[], [{"direction": "DEBIT", "account": "银行", "amount": 0}],
    [{"direction": "UNKNOWN", "account": "银行", "amount": 100}],
    [{"direction": "DEBIT", "account": "", "amount": 1}, {"direction": "CREDIT", "account": "银行", "amount": 1}],
    [{"direction": "DEBIT", "account": "银行", "amount": -1}, {"direction": "CREDIT", "account": "银行", "amount": -1}]])
def test_invalid_balanced_vouchers_cannot_be_reviewed(client, scope, lines):
    service, typed, group, voucher = ready_voucher(client, scope)
    response = command(client, scope, "revise_voucher", voucher["object_id"], voucher["version"], "invalid-lines-test", {"lines": lines})
    if response.status_code == 200:
        changed = response.json()["effect"]["object"]
        response = command(client, scope, "validate_draft", changed["object_id"], changed["version"], "invalid-validate-test")
    assert response.status_code == 409, response.text
    assert not service.store.list_objects(ObjectType.VOUCHER_VERSION.value, typed, statuses=["LOCALLY_CONFIRMED"])


def test_released_version_is_pinned_and_exported_voucher_is_immutable(client, scope):
    service, typed, group, voucher, exported = exported_package(client, scope)
    assert exported["package"]["data"]["voucher_version"] == voucher["version"]
    assert exported["export"]["data"]["voucher_version"] == voucher["version"]
    assert exported["export"]["data"]["lines"] == voucher["data"]["lines"]
    response = command(client, scope, "revise_voucher", voucher["object_id"], voucher["version"], "revise-exported-test", {"lines": voucher["data"]["lines"]})
    assert response.status_code == 409


def test_locked_period_rejects_commands_not_just_uploads(client, scope):
    service, typed, group, voucher, exported = exported_package(client, scope)
    p = exported["package"]
    service.ack_external_import(typed, package_id=p["object_id"], actor_id="alice", payload=receipt_for(p))
    period = service.workbench(typed)["period"]
    period = service.close_period(typed, actor_id="alice", expected_version=period["version"])
    service.lock_period(typed, actor_id="alice", expected_version=period["version"])
    group = service.store.get_object(group["object_id"], typed)
    assert command(client, scope, "suspend_group", group["object_id"], group["version"], "suspend-locked-test").status_code == 409
    assert client.post("/api/v1/business/procurement", json={"scope": scope, "fact_ids": group["data"]["member_fact_ids"], "business_identity": "late-group"}).status_code == 409


def test_fact_revision_invalidates_old_reconciliation_and_voucher(client, scope):
    service, typed, group, voucher = ready_voucher(client, scope)
    invoice = next(f for f in service.store.list_objects(ObjectType.FACT_RECORD.value, typed) if f["data"]["record_type"] == "INVOICE")
    changed = {**invoice["data"]["normalized_value"], "invoice_total": 11300, "net_amount": 10000, "tax": 1300}
    service.reparse_fact(typed, fact_id=invoice["object_id"], expected_version=invoice["version"], actor_id="alice", parser_version="test-v2", normalized_value=changed)
    response = command(client, scope, "validate_draft", voucher["object_id"], voucher["version"], "stale-basis-validate")
    assert response.status_code == 409
    response = command(client, scope, "generate_draft", group["object_id"], service.store.get_object(group["object_id"], typed)["version"], "stale-basis-generate")
    assert response.status_code == 409


def test_source_disposition_change_invalidates_previous_delivery_permission(client, scope):
    service, typed, group, voucher = ready_voucher(client, scope)
    voucher = service.validate_draft(typed, voucher_id=voucher["object_id"], expected_version=voucher["version"], actor_id="alice")
    source = service.store.list_objects(ObjectType.SOURCE_ARTIFACT.value, typed)[0]
    service.archive_artifact(typed, artifact_id=source["object_id"], expected_version=source["version"], actor_id="alice")
    latest = service.store.get_object(group["object_id"], typed)
    assert command(client, scope, "release_delivery", group["object_id"], latest["version"], "archived-source-release").status_code == 409


@pytest.mark.parametrize("field,value", [("account", {"invalid": "account"}), ("source_group_id", "foreign-group"), ("line_no", True)])
def test_voucher_line_schema_and_source_are_enforced(client, scope, field, value):
    service, typed, group, voucher = ready_voucher(client, scope)
    lines = [{**line, field: value} for line in voucher["data"]["lines"]]
    response = command(client, scope, "revise_voucher", voucher["object_id"], voucher["version"], "invalid-line-schema", {"lines": lines})
    assert response.status_code == 409


@pytest.mark.parametrize("field", ["export_id", "voucher_version_id", "voucher_version"])
def test_receipt_cannot_be_rebound_to_another_export_or_version(client, scope, field):
    service, typed, group, voucher, exported = exported_package(client, scope)
    p = exported["package"]
    payload = {**receipt_for(p), field: "other-export-value"}
    response = command(client, scope, "ack_external_import", p["object_id"], p["version"], "mismatched-receipt", payload)
    assert response.status_code == 409
    assert not service.store.list_objects(ObjectType.EXTERNAL_RECEIPT.value, typed)


def test_legacy_unpinned_export_is_not_accepted_as_success(client, scope):
    service, typed, group, voucher, exported = exported_package(client, scope)
    p = exported["package"]
    data = {key: value for key, value in p["data"].items() if key != "voucher_version"}
    # Reproduce old persisted records without altering current service code paths.
    legacy = service.store.revise_object(p["object_id"], p["version"], typed, data, status="EXPORT_CREATED", created_by="fixture")
    assert command(client, scope, "export_package", legacy["object_id"], legacy["version"], "legacy-export-test").status_code == 409
    assert command(client, scope, "ack_external_import", legacy["object_id"], legacy["version"], "legacy-ack-test", receipt_for(p)).status_code == 409
