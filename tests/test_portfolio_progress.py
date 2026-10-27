from app.ontology.contracts import Scope
from test_autonomous_workflow import setup, nonblocking_result, unresolved_decision
import pytest


def compare(service, scope):
    view = service.workbench(scope)
    item = service.portfolio([scope])['scopes'][0]
    w = view['autonomous_workflow']
    summary = item['work_summary']
    assert summary['status'] == w['status']
    assert summary['label'] == w['label']
    assert item['progress'] == view['progress']
    assert summary['todo_count'] == len([f for f in w['findings'] if f['needs_user']])
    assert summary['review_count'] == max(0, w['ready_count'] - w['confirmed_count'])
    assert summary['confirmed_count'] == w['confirmed_count']
    assert summary['pending_voucher_count'] == w['pending_count']
    assert summary['blocked_count'] == w['blocked_count']
    assert item['pending_confirmation_cards'] == summary['todo_count']
    assert item['autonomous_workflow']['label'] == w['label']
    assert 'findings' not in item['autonomous_workflow']
    return summary


@pytest.mark.parametrize('status', ['QUEUED', 'ANALYZING', 'REVIEWING', 'BLOCKED', 'CANCELLED'])
def test_portfolio_uses_current_workflow_instead_of_legacy_run(setup, status):
    _, service, scope, _, _, _ = setup
    w = service.autonomous
    w._revise(scope, w.current(scope), status, {})
    summary = compare(service, scope)
    assert summary['status'] == status
    assert summary['review_count'] == 0


def test_portfolio_retains_nonblocking_todos_and_updates_review_count(setup):
    _, service, scope, _, mature, result = setup
    w = service.autonomous
    w.runner = lambda *args: nonblocking_result(result)
    mature(); assert w.tick(scope)
    summary = compare(service, scope)
    assert summary['todo_count'] == summary['review_count'] == 1
    voucher = service.workbench(scope)['vouchers'][0]
    service.validate_draft(scope, voucher_id=voucher['object_id'], actor_id='alice', expected_version=1)
    summary = compare(service, scope)
    assert summary['review_count'] == 0 and summary['todo_count'] == 1
    assert summary['confirmed_count'] == 1
    w._revise(scope, w.current(scope), 'ACCEPTED', {'fingerprint': 'outdated'})
    summary = compare(service, scope)
    assert summary['status'] == 'STALE'
    assert summary['review_count'] == summary['todo_count'] == 0


def test_pending_findings_and_vouchers_are_separate_counts(setup):
    _, service, scope, _, mature, result = setup
    def pending(*args):
        r = result(); d = r['delivery']; ref = d['entries'][0]['source']
        d['findings'] = [dict(id='purpose', title='用途待核实', detail='缺业务用途', needs_user=True,
            evidence=[ref], affected_vouchers=['候选001'], decision=unresolved_decision('对应什么业务？', '未提供业务用途'))]
        d['voucher_assessments'][0].update(status='NEEDS_EVIDENCE', finding_ids=['purpose'])
        r['review'].update(ready_vouchers=[], reviewed_decisions=['purpose'])
        return r
    service.autonomous.runner = pending
    mature(); assert service.autonomous.tick(scope)
    summary = compare(service, scope)
    assert summary['todo_count'] == summary['pending_voucher_count'] == 1
    assert summary['review_count'] == 0


def test_empty_enterprise_does_not_reuse_another_company_status(setup):
    _, service, scope, _, mature, _ = setup
    mature(); assert service.autonomous.tick(scope)
    other = scope.model_copy(update={'legal_entity_id': 'another-company'})
    service.create_scope(other)
    summary = compare(service, other)
    assert summary['status'] == 'WAITING_INPUT' and summary['source_count'] == 0
    assert len(service.portfolio([other])['scopes']) == 1


def test_legacy_portfolio_keeps_its_own_workbench_progress(app, scope):
    service = app.state.service; typed = Scope(**scope); service.create_scope(typed)
    view = service.workbench(typed)
    item = service.portfolio([typed])['scopes'][0]
    assert item['progress'] == view['progress']
    assert item['work_summary']['mode'] == 'LEGACY'
    assert item['work_summary']['todo_count'] == len(view['pending_confirmation_cards'])
    assert item['autonomous_workflow'] is None
