"""Human handling records never substitute for the original balance checks."""
from copy import deepcopy

import pytest

from app.ontology.contracts import Scope
from app.ontology.errors import DomainError
from test_historical_preparation import unmapped_workbooks, upload


@pytest.fixture
def case(client, scope):
    service = client.app.state.service
    typed = Scope(**{**scope, "accounting_period_id": "2026-01"})
    service.create_scope(typed)
    for name, data in zip(("余额.xlsx", "序时.xlsx"), unmapped_workbooks()):
        upload(service, typed, data, name)
    service.historical.run_once()
    job = service.historical.view(typed)
    issue = job["data"]["result"]["issues"][0]
    row = issue["evidence"]["rows"][0]
    payload = {"issue_key": issue["issue_key"], "expected_plan_version": 0,
               "route": "existing_evidence", "conclusion": "需要复核调整对应关系",
               "action_plan": "核对同张凭证和期末余额，不直接冲销", "owner": "负责会计",
               "follow_up": "复核后补充余额依据",
               "evidence": [{"artifact_id": row["source"]["artifact_id"], "version": row["source"]["version"],
                             "anchor": row["anchor"]}]}
    return service, typed, job, payload


def execute(case, action, payload, *, target=None, actor="alice", role="accountant", key="save"):
    service, scope, job, _ = case
    target = target or job
    return service.execute_command(scope, action=action, target_id=target["object_id"],
        target_version=target["version"], idempotency_key=key, actor_id=actor, role=role, payload=payload)


def test_save_review_and_replay_never_release_original_gate(case):
    service, scope, job, payload = case
    before = service.historical.get(scope)
    result = execute(case, "save_historical_issue_plan", payload)
    plan = result["effect"]["object"]
    assert plan["status"] == "SUBMITTED" and plan["data"]["submitted_by"] == "alice"
    assert plan["data"]["evidence"][0]["sha256"]
    assert execute(case, "save_historical_issue_plan", payload)["idempotent"]
    with pytest.raises(DomainError, match="另一位"):
        execute(case, "review_historical_issue_plan", {"decision": "approved", "note": "同意"}, target=plan, key="self")
    reviewed = execute(case, "review_historical_issue_plan", {"decision": "approved", "note": "方案已复核，余额仍需校验"},
                       target=plan, actor="bob", role="reviewer", key="review")["effect"]["object"]
    assert reviewed["status"] == "REVIEWED"
    assert reviewed["data"]["review"]["reviewed_by"] == "bob"
    assert service.historical.get(scope) == before
    workbench = service.workbench(scope)
    assert workbench["historical_issue_plans"][0]["stale"] is False
    assert workbench["baseline"]["status"] == "DRAFT" and not workbench["vouchers"]
    flags = {k: True for k in ["completeness_confirmed", "final_close_confirmed", "carry_forward_confirmed"]}
    with pytest.raises(DomainError):
        service.confirm_baseline(scope, actor_id="bob", expected_version=1,
            payload={**flags, "historical_preparation": {"object_id": job["object_id"], "version": job["version"]}})


def test_unavailable_record_revision_return_and_ownership(case):
    service, scope, _, payload = case
    unavailable = {**payload, "route": "unavailable", "evidence": []}
    plan = execute(case, "save_historical_issue_plan", unavailable)["effect"]["object"]
    assert plan["status"] == "UNAVAILABLE_RECORDED"
    data = service.workbench(scope)["historical_issue_plans"][0]["data"]
    assert data["owner"] == "alice" and data["follow_up"] == "" and data["action_plan"] == ""
    with pytest.raises(DomainError):
        execute(case, "save_historical_issue_plan", {**payload, "expected_plan_version": 1}, actor="eve", key="foreign-editor")
    submitted = execute(case, "save_historical_issue_plan", {**payload, "expected_plan_version": 1}, key="resubmit")["effect"]["object"]
    returned = execute(case, "review_historical_issue_plan", {"decision": "returned", "note": "请补充对应余额行"},
                       target=submitted, actor="bob", role="reviewer", key="return")["effect"]["object"]
    assert returned["status"] == "RETURNED"
    resubmitted = execute(case, "save_historical_issue_plan", {**payload, "expected_plan_version": 3}, key="resubmit-again")["effect"]["object"]
    assert resubmitted["status"] == "SUBMITTED" and "review" not in resubmitted["data"]
    assert len(service.store.list_objects("HistoricalIssuePlan", scope, latest_only=False)) == 4


def test_unavailable_requires_only_reason_and_server_assigns_owner(case):
    service, scope, job, payload = case
    minimal = {"issue_key": payload["issue_key"], "expected_plan_version": 0,
               "route": "unavailable", "conclusion": "  客户暂无法提供其他材料  "}
    before = service.historical.get(scope)
    plan = execute(case, "save_historical_issue_plan", minimal)["effect"]["object"]
    assert plan["data"]["conclusion"] == "客户暂无法提供其他材料"
    assert plan["data"]["owner"] == plan["data"]["submitted_by"] == "alice"
    assert plan["data"]["action_plan"] == plan["data"]["follow_up"] == ""
    assert plan["data"]["evidence"] == []
    assert execute(case, "save_historical_issue_plan", minimal)["idempotent"]
    # Older clients may still send an owner: it cannot override authenticated identity.
    updated = execute(case, "save_historical_issue_plan", {**minimal, "expected_plan_version": 1,
        "owner": "bob", "action_plan": "旧表单", "follow_up": "旧安排"}, key="legacy")["effect"]["object"]
    assert updated["data"]["owner"] == "alice"
    assert service.historical.get(scope) == before
    assert service.workbench(scope)["baseline"]["status"] == "DRAFT"


@pytest.mark.parametrize("reason", ["", "  ", "x" * 2001])
def test_unavailable_rejects_blank_or_excessive_reason(case, reason):
    with pytest.raises(DomainError, match="原因"):
        execute(case, "save_historical_issue_plan", {"issue_key": case[3]["issue_key"],
            "expected_plan_version": 0, "route": "unavailable", "conclusion": reason})
    assert not case[0].store.list_objects("HistoricalIssuePlan", case[1])


@pytest.mark.parametrize("change", [
    {"issue_key": "invented"}, {"expected_plan_version": 1}, {"expected_plan_version": True},
    {"conclusion": " "}, {"owner": ""}, {"follow_up": ""}, {"action_plan": ""},
    {"route": "force_pass"}, {"evidence": []}, {"release_baseline": True}, {"conclusion": "x" * 2001},
])
def test_invalid_plan_is_rejected_without_partial_record(case, change):
    service, scope, _, payload = case
    with pytest.raises(DomainError):
        execute(case, "save_historical_issue_plan", {**payload, **change})
    assert not service.store.list_objects("HistoricalIssuePlan", scope)


@pytest.mark.parametrize("change", [{"version": 99}, {"artifact_id": "unknown"},
    {"anchor": {"region": "序时账!第999999行", "row": 999999}},
    {"anchor": {"region": "其他!第6行", "row": 6}},
    {"anchor": {"region": "序时账!第6行", "row": True}}])
def test_evidence_binding_and_location_must_be_real(case, change):
    payload = deepcopy(case[3])
    payload["evidence"][0].update(change)
    with pytest.raises(DomainError):
        execute(case, "save_historical_issue_plan", payload)


def test_stale_source_and_candidate_require_new_review(case):
    service, scope, job, payload = case
    plan = execute(case, "save_historical_issue_plan", payload)["effect"]["object"]
    service.historical.enqueue(scope, "alice", retry=True)
    service.historical.run_once()
    assert service.workbench(scope)["historical_issue_plans"][0]["stale"]
    with pytest.raises(DomainError):
        execute(case, "review_historical_issue_plan", {"decision": "approved", "note": "复核"}, target=plan, actor="bob", key="stale-review")
    with pytest.raises(DomainError):
        execute(case, "save_historical_issue_plan", {**payload, "expected_plan_version": 1}, key="stale-submit")
    # File tampering must also fail, even when object and job versions did not change.
    fresh_job = service.historical.view(scope)
    source = service.store.get_object(payload["evidence"][0]["artifact_id"], scope)
    (service.store.database.settings.storage_path/source["data"]["storage_path"]).write_bytes(b"tampered")
    with pytest.raises(DomainError):
        execute(case, "save_historical_issue_plan", payload, target=fresh_job, key="tampered")


def test_scope_role_and_closed_period_guards(case):
    service, scope, job, payload = case
    for role in ["viewer", "reviewer"]:
        with pytest.raises(DomainError):
            execute(case, "save_historical_issue_plan", payload, role=role, key=role)
    plan = execute(case, "save_historical_issue_plan", payload)["effect"]["object"]
    with pytest.raises(DomainError):
        execute(case, "review_historical_issue_plan", {"decision": "approved", "note": "复核"}, target=plan, actor="bob", role="operator", key="operator-review")
    other = Scope(**{**scope.model_dump(), "legal_entity_id": "other"})
    service.create_scope(other)
    assert service.workbench(other)["historical_issue_plans"] == []
    with pytest.raises(DomainError):
        service.execute_command(other, action="save_historical_issue_plan", target_id=job["object_id"],
            target_version=job["version"], idempotency_key="cross-scope", actor_id="alice", role="accountant", payload=payload)
    period = service.workbench(scope)["period"]
    service.store.revise_object(period["object_id"], period["version"], scope, period["data"], status="CLOSED", created_by="fixture")
    with pytest.raises(DomainError):
        execute(case, "review_historical_issue_plan", {"decision": "approved", "note": "复核"}, target=plan, actor="bob", key="closed")


def test_http_plan_contract_and_error_response(client, case):
    _, scope, job, payload = case
    body = {"action": "save_historical_issue_plan", "target_id": job["object_id"], "target_version": job["version"],
            "scope": scope.model_dump(), "idempotency_key": "http-plan-submit", "payload": payload}
    response = client.post("/api/v1/commands", json=body, headers={"X-Role": "accountant", "X-Actor-Id": "alice"})
    assert response.status_code == 200 and response.json()["effect"]["object"]["status"] == "SUBMITTED"
    body.update(idempotency_key="invalid-http", payload={**payload, "conclusion": None})
    rejected = client.post("/api/v1/commands", json=body, headers={"X-Role": "accountant"})
    assert rejected.status_code in {409, 422}
