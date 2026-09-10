from concurrent.futures import ThreadPoolExecutor

import pytest

from app.ontology.contracts import Scope
from app.ontology.errors import DomainError


def setup_command(app, scope):
    service = app.state.service
    typed = Scope(**scope)
    service.create_scope(typed, actor_id="alice")
    baseline = service.workbench(typed)["baseline"]
    args = dict(scope=typed, action="confirm_baseline", target_id=baseline["object_id"],
                target_version=baseline["version"], idempotency_key="baseline-test-001", actor_id="alice",
                role="accountant", payload=service._demo_baseline_payload(typed, "fixture"))
    return service, typed, args


def test_cached_commands_cannot_cross_scope_actor_role_or_payload(app, scope):
    service, typed, args = setup_command(app, scope)
    first = service.execute_command(**args)
    assert service.execute_command(**args)["idempotent"] is True
    for changes, code in [({"scope": typed.model_copy(update={"ledger_id": "foreign"})}, "SCOPE_VIOLATION"),
                          ({"actor_id": "bob"}, "SCOPE_VIOLATION"),
                          ({"role": "viewer"}, "PERMISSION_DENIED"),
                          ({"payload": {"opening_balance_source": "changed"}}, "IDEMPOTENCY_CONFLICT")]:
        with pytest.raises(DomainError) as exc:
            service.execute_command(**{**args, **changes})
        assert exc.value.code == code
    assert app.state.store.find_command(args["idempotency_key"])["effect"] == first["effect"]


def test_rejected_command_replay_is_still_rejected(app, scope):
    service, typed, args = setup_command(app, scope)
    args["role"] = "viewer"
    for _ in range(2):
        with pytest.raises(DomainError) as exc:
            service.execute_command(**args)
        assert exc.value.status_code == 403
    args["role"] = "accountant"
    with pytest.raises(DomainError) as exc:
        service.execute_command(**args)
    assert exc.value.status_code == 403
    assert service.workbench(typed)["baseline"]["version"] == 1


def test_effect_and_success_audit_rollback_together(app, scope, monkeypatch):
    service, typed, args = setup_command(app, scope)
    original = app.state.store.add_audit

    def fail_success(event_type, *a, **kw):
        if event_type == "COMMAND_SUCCEEDED":
            raise RuntimeError("simulated audit storage failure")
        return original(event_type, *a, **kw)

    monkeypatch.setattr(app.state.store, "add_audit", fail_success)
    with pytest.raises(RuntimeError):
        service.execute_command(**args)
    assert service.workbench(typed)["baseline"]["version"] == 1
    assert app.state.store.find_command(args["idempotency_key"]) is None
    assert not any(a["event_type"] == "BASELINE_CONFIRMED" for a in app.state.store.list_audits(typed))
    monkeypatch.setattr(app.state.store, "add_audit", original)
    assert service.execute_command(**args)["effect"]["object"]["version"] == 2


def test_parallel_duplicates_have_one_effect_and_stale_writes_conflict(app, scope):
    service, typed, args = setup_command(app, scope)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: service.execute_command(**args), range(4)))
    assert sum(not r["idempotent"] for r in results) == 1
    assert service.workbench(typed)["baseline"]["version"] == 2
    with pytest.raises(DomainError) as exc:
        service.execute_command(**{**args, "idempotency_key": "baseline-stale-test"})
    assert exc.value.code == "VERSION_CONFLICT"


def test_command_cannot_use_same_version_unrelated_object_as_target(app, scope):
    service, typed, args = setup_command(app, scope)
    period = service.workbench(typed)["period"]
    with pytest.raises(DomainError) as exc:
        service.execute_command(**{**args, "target_id": period["object_id"]})
    assert exc.value.code == "PRECONDITION_FAILED"
    assert service.workbench(typed)["baseline"]["status"] == "DRAFT"
