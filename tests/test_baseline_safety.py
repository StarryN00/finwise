import base64
from copy import deepcopy
from dataclasses import replace

import pytest

from app.ontology.contracts import ArtifactInput, Scope
from app.ontology.errors import PermissionDenied, PreconditionFailed
from conftest import command
from test_delivery_safety import ready_voucher, exported_package, receipt_for


def baseline_input(service, scope):
    service.create_scope(scope, actor_id="fixture")
    source = service.create_artifact(ArtifactInput(scope=scope, filename="2026-02-closing-fixture.txt",
        content_base64=base64.b64encode(b"SYNTHETIC: February closed; cash debit 1000; capital credit 1000.").decode(),
        observed_period="2026-02", source_channel="TEST"), actor_id="fixture")
    ref = {"artifact_id": source["object_id"], "version": source["version"], "anchor": {"row": 1}}
    return {"prior_period": "2026-02", "close_reference": "SYNTHETIC-CLOSE-02", "balance_source": ref, "close_source": ref,
        "completeness_confirmed": True, "currency": "CNY", "balances": [
            {"account_code": "1001", "account_name": "库存现金", "closing_debit": "1000.00", "closing_credit": "0.00",
             "opening_debit": "1000.00", "opening_credit": "0.00", "source_anchor": {"row": 1}, "requires_auxiliary": False, "auxiliary": []},
            {"account_code": "4001", "account_name": "实收资本", "closing_debit": "0.00", "closing_credit": "1000.00",
             "opening_debit": "0.00", "opening_credit": "1000.00", "source_anchor": {"row": 2}, "requires_auxiliary": False, "auxiliary": []}]}


def confirm(client, scope, payload, key="baseline-confirm-check"):
    obj = client.app.state.service.workbench(Scope(**scope))["baseline"]
    return command(client, scope, "confirm_baseline", obj["object_id"], obj["version"], key, payload)


def test_baseline_confirmation_pins_sources_rows_and_deterministic_checks(client, scope):
    service, typed = client.app.state.service, Scope(**scope)
    payload = baseline_input(service, typed)
    response = confirm(client, scope, payload)
    assert response.status_code == 200, response.text
    baseline = response.json()["effect"]["object"]
    assert baseline["data"]["validation_version"] == "baseline-v1"
    assert baseline["data"]["balance_totals"] == {"debit": "1000.00", "credit": "1000.00"}
    assert baseline["data"]["confirmed_inputs"]["balances"] == payload["balances"]
    service._require_baseline_confirmed(typed)
    before = service.store.get_object(baseline["object_id"], typed, 1)
    assert before["status"] == "DRAFT" and before["data"]["opening_balance_verified"] is False


def test_public_contract_declares_required_baseline_inputs(client):
    response = client.get("/api/v1/ontology/contract")
    assert response.status_code == 200
    contract = response.json()
    assert contract["contract_version"] == "ontology-v1.2"
    assert contract["baseline_validation_version"] == "baseline-v1"
    required = contract["baseline_confirmation_schema"]["required"]
    assert {"prior_period", "balance_source", "close_source", "balances", "completeness_confirmed"} <= set(required)


@pytest.mark.parametrize("mutation", [
    lambda p: p.clear(),
    lambda p: p.update(balances=[]),
    lambda p: p.update(completeness_confirmed=False),
    lambda p: p.update(completeness_confirmed=1),
    lambda p: p.update(prior_period="2025-12"),
    lambda p: p.update(close_reference=""),
    lambda p: p.update(confirmed_by="forged"),
    lambda p: p["balances"][0].update(opening_debit="999.99"),
    lambda p: p["balances"][0].update(opening_debit="NaN"),
    lambda p: p["balances"][0].update(opening_debit=True),
    lambda p: p["balances"][0].update(source_anchor={}),
    lambda p: p["balances"][0].update(requires_auxiliary=True),
    lambda p: p["balances"].pop(),
    lambda p: p["balances"].append(deepcopy(p["balances"][0])),
    lambda p: p["balance_source"].update(version=True),
    lambda p: p["close_source"].update(anchor={}),
])
def test_invalid_baseline_never_becomes_confirmed(client, scope, mutation):
    service, typed = client.app.state.service, Scope(**scope)
    payload = baseline_input(service, typed)
    mutation(payload)
    response = confirm(client, scope, payload)
    assert response.status_code == 409, response.text
    baseline = service.workbench(typed)["baseline"]
    assert baseline["status"] == "DRAFT" and baseline["version"] == 1


def test_auxiliary_balances_must_match_each_control_account(client, scope):
    service, typed = client.app.state.service, Scope(**scope)
    payload = baseline_input(service, typed)
    row = payload["balances"][0]
    row["requires_auxiliary"] = True
    row["auxiliary"] = [{"key": "现金账户-A", "closing_debit": "1000.00", "closing_credit": "0.00",
                          "opening_debit": "1000.00", "opening_credit": "0.00", "source_anchor": {"row": 3}}]
    invalid = deepcopy(payload)
    invalid["balances"][0]["auxiliary"][0].update(opening_debit="999.00", closing_debit="999.00")
    assert confirm(client, scope, invalid, "baseline-aux-invalid").status_code == 409
    response = confirm(client, scope, payload, "baseline-aux-valid")
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("reason", ["archived", "modified_file", "wrong_period", "wrong_type", "foreign_scope"])
def test_baseline_sources_are_checked_and_cannot_be_replaced_by_arbitrary_ids(client, scope, reason):
    service, typed = client.app.state.service, Scope(**scope)
    payload = baseline_input(service, typed)
    source = service.store.get_object(payload["balance_source"]["artifact_id"], typed)
    if reason == "archived":
        service.archive_artifact(typed, artifact_id=source["object_id"], expected_version=source["version"], actor_id="fixture")
    elif reason == "modified_file":
        path = service.store.database.settings.storage_path / source["data"]["storage_path"]
        path.write_bytes(b"TAMPERED SYNTHETIC FILE")
    elif reason == "wrong_period":
        value = deepcopy(source["data"])
        value["observed_period"] = "2025-12"
        source = service.store.revise_object(source["object_id"], source["version"], typed, value, status="PERIOD_EXCEPTION", created_by="fixture")
        payload["balance_source"]["version"] = source["version"]
    elif reason == "wrong_type":
        payload["balance_source"]["artifact_id"] = service.workbench(typed)["period"]["object_id"]
    else:
        foreign = typed.model_copy(update={"legal_entity_id": "foreign"})
        other = baseline_input(service, foreign)
        payload["balance_source"] = other["balance_source"]
    assert confirm(client, scope, payload).status_code in {403, 409}


def test_confirmed_baseline_is_revalidated_before_accounting_and_legacy_flag_is_not_enough(client, scope):
    service, typed = client.app.state.service, Scope(**scope)
    payload = baseline_input(service, typed)
    assert confirm(client, scope, payload).status_code == 200
    source = service.store.get_object(payload["balance_source"]["artifact_id"], typed)
    service.archive_artifact(typed, artifact_id=source["object_id"], expected_version=source["version"], actor_id="fixture")
    with pytest.raises(PreconditionFailed):
        service._require_baseline_confirmed(typed)
    baseline = service.workbench(typed)["baseline"]
    service.store.revise_object(baseline["object_id"], baseline["version"], typed,
        {"opening_balance_verified": True}, status="CONFIRMED", created_by="legacy-fixture")
    with pytest.raises(PreconditionFailed):
        service._require_baseline_confirmed(typed)


@pytest.mark.parametrize("action", ["generate_draft", "validate_draft", "release_delivery", "export_package"])
def test_invalidated_baseline_blocks_subsequent_accounting_commands(client, scope, action):
    service, typed, group, voucher = ready_voucher(client, scope)
    target = voucher if action == "validate_draft" else group
    if action in {"release_delivery", "export_package"}:
        service.validate_draft(typed, voucher_id=voucher["object_id"], expected_version=voucher["version"], actor_id="reviewer")
    if action == "export_package":
        target = service.release_delivery(typed, group_id=group["object_id"], actor_id="reviewer")
    baseline = service.workbench(typed)["baseline"]
    source = service.store.get_object(baseline["data"]["opening_balance_source"]["artifact_id"], typed)
    service.archive_artifact(typed, artifact_id=source["object_id"], expected_version=source["version"], actor_id="alice")
    target = service.store.get_object(target["object_id"], typed)
    response = command(client, scope, action, target["object_id"], target["version"], "invalid-baseline-" + action)
    assert response.status_code == 409, response.text
    assert "基线来源" in response.text


def test_invalid_baseline_preserves_existing_export_but_prevents_period_close(client, scope):
    service, typed, _, _, exported = exported_package(client, scope)
    package = exported["package"]
    baseline = service.workbench(typed)["baseline"]
    source = service.store.get_object(baseline["data"]["opening_balance_source"]["artifact_id"], typed)
    service.archive_artifact(typed, artifact_id=source["object_id"], expected_version=source["version"], actor_id="alice")
    response = command(client, scope, "export_package", package["object_id"], package["version"], "existing-export-replay")
    assert response.status_code == 200, response.text
    assert response.json()["effect"]["export"] == exported["export"]
    service.ack_external_import(typed, package_id=package["object_id"], actor_id="alice", payload=receipt_for(package))
    period = service.workbench(typed)["period"]
    response = command(client, scope, "close_period", period["object_id"], period["version"], "invalid-baseline-close")
    assert response.status_code == 409 and "基线来源" in response.text
    assert service.workbench(typed)["period"]["status"] == "OPEN"


@pytest.mark.parametrize("reconcile_again", [False, True])
def test_reconfirmed_baseline_cannot_close_using_pre_revision_vouchers(client, scope, reconcile_again):
    service, typed, group, _, exported = exported_package(client, scope)
    package = exported["package"]
    service.ack_external_import(typed, package_id=package["object_id"], actor_id="alice", payload=receipt_for(package))
    baseline = service.workbench(typed)["baseline"]
    assert confirm(client, scope, baseline["data"]["confirmed_inputs"], "reconfirm-after-export").status_code == 200
    if reconcile_again:
        service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    period = service.workbench(typed)["period"]
    response = command(client, scope, "close_period", period["object_id"], period["version"], "close-with-old-baseline")
    assert response.status_code == 409, response.text
    assert service.workbench(typed)["period"]["status"] == "OPEN"


@pytest.mark.parametrize("period_status", ["OPEN", "CLOSED", "ARCHIVED", "LOCKED"])
def test_fixed_export_can_be_retrieved_after_import_or_close_without_mutating_accounting(client, scope, period_status):
    service, typed, _, _, exported = exported_package(client, scope)
    package = exported["package"]
    package = service.ack_external_import(typed, package_id=package["object_id"], actor_id="alice", payload=receipt_for(package))["package"]
    if period_status != "OPEN":
        period = service.workbench(typed)["period"]
        period = service.close_period(typed, actor_id="alice", expected_version=period["version"])
        if period_status == "ARCHIVED":
            service.archive_period(typed, actor_id="alice", expected_version=period["version"])
        if period_status == "LOCKED":
            service.lock_period(typed, actor_id="alice", expected_version=period["version"])
    before = service.store.list_objects(None, typed, latest_only=False)
    response = command(client, scope, "export_package", package["object_id"], package["version"], "retrieve-fixed-export")
    assert response.status_code == 200, response.text
    assert response.json()["effect"]["export"] == exported["export"]
    assert service.store.list_objects(None, typed, latest_only=False) == before


def test_new_export_remains_forbidden_in_locked_period(client, scope):
    service, typed, group, voucher = ready_voucher(client, scope)
    service.validate_draft(typed, voucher_id=voucher["object_id"], expected_version=voucher["version"], actor_id="reviewer")
    package = service.release_delivery(typed, group_id=group["object_id"], actor_id="reviewer")
    period = service.workbench(typed)["period"]
    # Model a persisted locked scope without an existing export; retrieval exemption must not generate one.
    service.store.revise_object(period["object_id"], period["version"], typed, period["data"], status="LOCKED", created_by="fixture")
    response = command(client, scope, "export_package", package["object_id"], package["version"], "no-new-locked-export")
    assert response.status_code == 409


@pytest.mark.parametrize("entry", ["create_procurement_demo", "_demo_baseline_payload"])
def test_synthetic_baseline_helpers_refuse_authenticated_instances_before_writing(client, scope, entry, monkeypatch):
    service, typed = client.app.state.service, Scope(**scope)
    database = service.store.database
    monkeypatch.setattr(database, "settings", replace(database.settings, require_auth=True))
    with pytest.raises(PermissionDenied):
        getattr(service, entry)(typed, actor_id="fixture")
    assert service.store.list_objects(None, typed, latest_only=False) == []
    assert list(database.settings.storage_path.rglob("*.bin")) == []


def test_baseline_revision_requires_new_reconciliation_and_new_voucher_revision(client, scope):
    service, typed, group, voucher = ready_voucher(client, scope)
    baseline = service.workbench(typed)["baseline"]
    response = confirm(client, scope, baseline["data"]["confirmed_inputs"], "reconfirm-baseline")
    assert response.status_code == 200, response.text
    assert response.json()["effect"]["object"]["version"] == baseline["version"] + 1
    response = command(client, scope, "validate_draft", voucher["object_id"], voucher["version"], "baseline-old-recon")
    assert response.status_code == 409, response.text
    service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    response = command(client, scope, "validate_draft", voucher["object_id"], voucher["version"], "baseline-old-voucher")
    assert response.status_code == 409 and "请重新生成修订版本" in response.text
    revised = service.generate_draft(typed, group_id=group["object_id"], actor_id="alice")
    assert revised["object_id"] == voucher["object_id"] and revised["version"] > voucher["version"]
    checked = service.validate_draft(typed, voucher_id=revised["object_id"], expected_version=revised["version"], actor_id="reviewer")
    assert checked["status"] == "LOCALLY_CONFIRMED"
    assert service.store.get_object(voucher["object_id"], typed, voucher["version"]) == voucher


def test_january_baseline_requires_previous_december(client, scope):
    scope = {**scope, "accounting_period_id": "2026-01", "baseline_id": "baseline-january"}
    typed, service = Scope(**scope), client.app.state.service
    service.create_scope(typed, actor_id="fixture")
    payload = service._demo_baseline_payload(typed, "fixture")
    assert payload["prior_period"] == "2025-12"
    invalid = {**payload, "prior_period": "2025-11"}
    assert confirm(client, scope, invalid, "january-not-november").status_code == 409
    response = confirm(client, scope, payload, "january-december")
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("anchor", [{"row": True}, {"row": 1.5}, {"page": False}])
def test_baseline_anchors_reject_non_integer_locations(client, scope, anchor):
    service, typed = client.app.state.service, Scope(**scope)
    payload = baseline_input(service, typed)
    payload["balance_source"]["anchor"] = anchor
    assert confirm(client, scope, payload).status_code == 409


def test_workbench_reports_effective_baseline_validity_without_rewriting_history(client, scope):
    service, typed, group, _ = ready_voucher(client, scope)
    before = service.workbench(typed)
    assert before["baseline_validation"]["status"] == "VALID"
    assert before["deliverable_groups"]
    baseline = before["baseline"]
    assert confirm(client, scope, baseline["data"]["confirmed_inputs"], "baseline-revision-summary").status_code == 200
    assert service.workbench(typed)["deliverable_groups"] == []
    service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    assert service.workbench(typed)["deliverable_groups"]
    source = service.store.get_object(baseline["data"]["opening_balance_source"]["artifact_id"], typed)
    service.archive_artifact(typed, artifact_id=source["object_id"], expected_version=source["version"], actor_id="alice")
    response = client.post("/api/v1/workbench", json={"scope": scope})
    assert response.status_code == 200
    actual = response.json()
    assert actual["baseline_validation"]["status"] == "INVALID"
    assert "基线来源" in actual["baseline_validation"]["reason"]
    assert actual["deliverable_groups"] == []
    assert actual["baseline"]["status"] == "CONFIRMED"
    assert service.store.get_object(baseline["object_id"], typed, baseline["version"]) == baseline
