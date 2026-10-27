"""Contract upgrades invalidate review authority without rewriting accounting history."""
from copy import deepcopy
from pathlib import Path
import socket
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from app import autonomous_workflow, review_loop
from test_autonomous_workflow import setup
from test_stage4_loop import decision_result


def test_duplicate_local_server_cannot_initialize_database_before_port_failure(tmp_path):
    database = tmp_path / 'must-not-exist.db'
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        process = subprocess.run(
            [sys.executable, 'scripts/serve_autonomous.py', '--database', str(database),
             '--storage', str(tmp_path / 'sources'), '--port', str(listener.getsockname()[1])],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
    assert process.returncode != 0
    assert 'Address already in use' in process.stderr
    assert not database.exists()
    assert not (tmp_path / 'sources').exists()


def contract_result(base, version=10, context=None):
    result = decision_result(base, context) if context is not None else base()
    result['review_policy_version'] = version
    result['delivery'].setdefault('settlement_matches', [])
    result['review'].setdefault('reviewed_settlement_matches', [])
    return result


def deploy_contract(monkeypatch, version):
    # Simulate the same persisted ledger before and after a server deployment.
    monkeypatch.setattr(autonomous_workflow, 'REVIEW_POLICY_VERSION', version)
    monkeypatch.setattr(review_loop, 'REVIEW_POLICY_VERSION', version)


def accepted_previous_contract(setup, monkeypatch, *, pending=False):
    _, service, scope, _, mature, base = setup
    workflow = service.autonomous
    deploy_contract(monkeypatch, 6)
    workflow.enqueue(scope, 'alice')
    workflow.runner = lambda *args: contract_result(
        base, 6, workflow.review_context(scope) if pending else None)
    mature()
    assert workflow.tick(scope)
    return deepcopy(workflow.current(scope))


@pytest.mark.parametrize('action', ['answer', 'decision', 'materials-complete'])
def test_contract_upgrade_rejects_answers_to_old_reviewed_questions(setup, monkeypatch, action):
    app, service, scope, source, _, _ = setup
    workflow = service.autonomous
    old = accepted_previous_contract(setup, monkeypatch, pending=True)
    source_before = deepcopy(service.store.get_object(source['object_id'], scope))
    old_source_key = workflow.source_key(scope)

    deploy_contract(monkeypatch, 10)
    # Deployment alone is sufficient: no new attachment, answer or run is needed.
    view = service.workbench(scope)
    assert view['autonomous_workflow']['stale']
    assert not view['autonomous_workflow']['accepted']
    assert workflow.inputs(scope)[0] != old['data']['fingerprint']
    assert workflow.source_key(scope) == old_source_key
    body = dict(scope=scope.model_dump(), run_id=old['object_id'])
    if action == 'answer':
        body.update(finding_id='nature', text='这笔款项需要归还')
    elif action == 'decision':
        body.update(finding_id='nature', option_id='loan', acknowledged=True)
    response = TestClient(app).post('/api/v1/autonomous/' + action, json=body)

    assert response.status_code == 409, response.text
    assert not service.store.list_objects('AutonomousAnswer', scope)
    assert not service.store.list_objects('VoucherVersion', scope)
    assert service.store.get_object(old['object_id'], scope) == old
    assert service.store.get_object(source['object_id'], scope) == source_before


def test_contract_upgrade_rejects_old_draft_confirmation_without_erasing_it(setup, monkeypatch):
    app, service, scope, _, _, _ = setup
    old_run = accepted_previous_contract(setup, monkeypatch)
    voucher = deepcopy(service.workbench(scope)['vouchers'][0])

    deploy_contract(monkeypatch, 10)
    assert not service.workbench(scope)['vouchers']
    command = dict(scope=scope.model_dump(), action='validate_draft', target_id=voucher['object_id'],
                   target_version=voucher['version'], idempotency_key='stale-contract-review', payload={})
    response = TestClient(app).post('/api/v1/commands', json=command)

    assert response.status_code == 409, response.text
    assert service.store.get_object(voucher['object_id'], scope) == voucher
    assert service.store.get_object(old_run['object_id'], scope) == old_run
    assert not any(a['event_type'] == 'AUTONOMOUS_HUMAN_REVIEW'
                   for a in service.store.list_audits(scope))
    assert not service.store.list_objects('DeliveryPackage', scope)


def test_identical_entries_require_fresh_human_review_after_contract_upgrade(setup, monkeypatch):
    _, service, scope, _, mature, base = setup
    workflow = service.autonomous
    old_run = accepted_previous_contract(setup, monkeypatch)
    old_voucher = service.workbench(scope)['vouchers'][0]
    confirmed = deepcopy(service.validate_draft(scope, voucher_id=old_voucher['object_id'],
                                                actor_id='alice', expected_version=1))
    sources_before = deepcopy(workflow.inputs(scope)[1])

    deploy_contract(monkeypatch, 10)
    new_run = workflow.enqueue(scope, 'alice')
    assert new_run['object_id'] != old_run['object_id']
    assert new_run['data']['parent_id'] == old_run['object_id']
    workflow.runner = lambda *args: contract_result(base)
    mature()
    assert workflow.tick(scope)
    current = service.workbench(scope)['vouchers'][0]

    assert (workflow.current(scope)['data']['result']['delivery']['entries']
            == old_run['data']['result']['delivery']['entries'])
    assert current['data']['assessment'] == confirmed['data']['assessment']
    assert workflow.inputs(scope)[1] == sources_before
    assert current['data']['review_basis'] != confirmed['data']['review_basis']
    assert current['status'] == 'DRAFT'
    assert not current['data']['formal_balance_impact']
    assert 'carried_from' not in current['data']
    assert 'validated_by' not in current['data']
    assert service.store.get_object(confirmed['object_id'], scope) == confirmed
    assert service.store.get_object(old_run['object_id'], scope) == old_run
    assert not any(a['event_type'] == 'AUTONOMOUS_REVIEW_CARRIED'
                   for a in service.store.list_audits(scope))
    assert not service.store.list_objects('DeliveryPackage', scope)

    # The new candidate remains usable through the ordinary explicit review action.
    reviewed = service.validate_draft(scope, voucher_id=current['object_id'],
                                      actor_id='alice', expected_version=1)
    assert reviewed['status'] == 'LOCALLY_CONFIRMED'
    assert not reviewed['data']['formal_balance_impact']


@pytest.mark.parametrize('version', [None, 1, 5, 6, 7, 8, 9])
def test_old_contract_result_is_rejected_despite_current_inputs_and_pass_verdict(setup, monkeypatch, version):
    _, service, scope, _, mature, base = setup
    workflow = service.autonomous
    deploy_contract(monkeypatch, 10)
    job = workflow.enqueue(scope, 'alice')
    result = contract_result(base, version)
    if version is None:
        result.pop('review_policy_version')
    workflow.runner = lambda *args: result
    assert job['data']['fingerprint'] == workflow.inputs(scope)[0]
    mature()

    assert not workflow.tick(scope)
    assert workflow.current(scope)['status'] == 'BLOCKED'
    assert not service.store.list_objects('VoucherVersion', scope)
    assert not service.store.list_objects('VoucherDraft', scope)
    assert not service.store.list_objects('DeliveryPackage', scope)


def test_inflight_old_contract_job_cannot_admit_after_upgrade_even_with_new_version_label(setup, monkeypatch):
    _, service, scope, _, mature, base = setup
    workflow = service.autonomous
    deploy_contract(monkeypatch, 6)
    old_job = workflow.enqueue(scope, 'alice')

    def finishes_after_deployment(folder, manifest, paths, context, settings, heartbeat, progress):
        assert context['review_loop_version'] == 6
        deploy_contract(monkeypatch, 10)
        workflow.enqueue(scope, 'alice')
        return contract_result(base, 10)

    workflow.runner = finishes_after_deployment
    mature()
    assert not workflow.tick(scope)
    assert service.store.get_object(old_job['object_id'], scope)['status'] == 'STALE'
    assert workflow.current(scope)['status'] == 'QUEUED'
    assert workflow.current(scope)['data']['parent_id'] == old_job['object_id']
    assert workflow.review_context(scope)['review_loop_version'] == 10
    assert not service.store.list_objects('VoucherVersion', scope)
    assert not service.store.list_objects('VoucherDraft', scope)

    workflow.runner = lambda *args: contract_result(base)
    mature()
    assert workflow.tick(scope)
    assert service.workbench(scope)['vouchers'][0]['status'] == 'DRAFT'
    assert service.store.get_object(old_job['object_id'], scope)['status'] == 'STALE'
