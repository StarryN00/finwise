"""Ledger-scoped policy lifecycle and independent, source-backed travel review gates."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.autonomous_checks import validate, settlement_match_errors
from app.autonomous_runtime import prepare
from app.ontology.contracts import Scope
from app.ontology.errors import PreconditionFailed
from app.review_loop import REVIEW_POLICY_VERSION, review_loop_errors
from app.travel_policy import travel_policy_errors, travel_policy_reviewed, policy_id
from test_autonomous_workflow import setup
from test_settlement_matches import settlement


def save(workflow, scope, *, version=0, enabled=True, note='用户转述代账已确认，按企业口径出草稿并人工复核'):
    return workflow.save_travel_policy(scope, 'alice', 'operator', enabled=enabled,
                                       expected_version=version, source_note=note)


def policy_result(base, context):
    result = base()
    result['review_policy_version'] = REVIEW_POLICY_VERSION
    result['delivery'].update(settlement_matches=[], travel_policy_applications=[])
    policy = context.get('travel_policy')
    result['review'].update(reviewed_settlement_matches=[], reviewed_travel_policy_applications=[],
                           reviewed_travel_policy={k:policy[k] for k in ('id', 'version')} if policy else None)
    return result


def test_policy_api_permission_version_audit_and_no_client_rules(setup):
    app, service, scope, _, _, _ = setup
    client = TestClient(app)
    body = dict(scope=scope.model_dump(), enabled=True, expected_version=0, source_note='代账确认记录')
    assert client.post('/api/v1/autonomous/travel-policy', json=body, headers={'X-Role':'viewer'}).status_code == 403
    for invalid in ({'enabled':'true'}, {'expected_version':True}, {'rules':{}}, {'confirmed_by':'forged'}):
        assert client.post('/api/v1/autonomous/travel-policy', json={**body, **invalid}).status_code == 422
    response = client.post('/api/v1/autonomous/travel-policy', json=body, headers={'X-Actor-Id':'confirmed-operator'})
    assert response.status_code == 200, response.text
    policy = response.json()['policy']
    assert policy['version'] == 1 and policy['confirmed_at']
    assert policy['confirmed_by'] == 'confirmed-operator'
    assert policy['rules']['allowance_monthly_limit'] is None
    assert policy['rules']['formal_posting'] is False
    assert client.post('/api/v1/autonomous/travel-policy', json=body).status_code == 409
    repeated = client.post('/api/v1/autonomous/travel-policy', json={**body, 'expected_version':1})
    assert repeated.status_code == 200 and repeated.json()['policy']['version'] == 1
    assert service.workbench(scope)['autonomous_workflow']['travel_policy']['id'] == policy['id']
    assert any(a['event_type']=='TRAVEL_POLICY_CONFIRMED' for a in service.store.list_audits(scope))
    assert not service.store.list_objects('DeliveryPackage', scope)


def test_authenticated_policy_api_rejects_other_enterprise_and_spoofed_identity(tmp_path, scope):
    from pathlib import Path
    from app.auth import create_user, grant_scope
    from app.config import Settings
    from app.main import create_app
    from test_scope_provisioning import login
    settings = Settings(root=Path(__file__).resolve().parents[1], database_path=tmp_path/'secured.db',
                        storage_path=tmp_path/'secured-data', require_auth=True, autonomous_enabled=True)
    app = create_app(settings)
    service = app.state.service
    own = Scope(**scope)
    other = Scope(**{**scope, 'legal_entity_id':'other-enterprise'})
    service.create_scope(own); service.create_scope(other)
    create_user(app.state.database, 'alice', 'correct-horse-battery', 'accountant')
    grant_scope(app.state.database, 'alice', own)
    client, headers = login(app, 'alice', 'correct-horse-battery')
    body = dict(scope=other.model_dump(), enabled=True, expected_version=0, source_note='确认')
    assert client.post('/api/v1/autonomous/travel-policy',json=body,headers=headers).status_code == 403
    body['scope'] = own.model_dump()
    assert client.post('/api/v1/autonomous/travel-policy',json=body).status_code == 403
    result = client.post('/api/v1/autonomous/travel-policy',json=body,headers={**headers,'X-Actor-Id':'impostor'})
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'SAVED' and result.json()['run_id'] is None
    assert result.json()['policy']['confirmed_by'] == 'alice'
    assert service.autonomous.travel_policy(other) is None


def test_policy_reused_across_months_but_never_other_ledger_or_entity(setup):
    _, service, scope, _, _, _ = setup
    workflow = service.autonomous
    policy, _ = save(workflow, scope)
    later = Scope(**{**scope.model_dump(), 'accounting_period_id':'2026-04', 'baseline_id':'new-baseline'})
    service.create_scope(later)
    assert workflow.review_context(later)['travel_policy'] == policy
    earlier = Scope(**{**scope.model_dump(), 'accounting_period_id':'2026-02'})
    assert workflow.travel_policy(earlier) is None
    for field in ('tenant_id', 'organization_id', 'legal_entity_id', 'ledger_id'):
        other = Scope(**{**scope.model_dump(), field:'different'})
        assert policy_id(other) != policy_id(scope)
        assert workflow.travel_policy(other) is None
    later_fp = workflow.inputs(later)[0]
    disabled, _ = save(workflow, scope, version=1, enabled=False, note='暂停使用企业默认口径')
    assert disabled['version'] == 2 and not disabled['enabled']
    assert workflow.inputs(later)[0] != later_fp
    assert workflow.review_context(later)['travel_policy'] is None
    assert workflow.travel_policy(later)['version'] == 2


def test_policy_change_invalidates_candidates_and_prior_human_review(setup):
    _, service, scope, _, mature, base = setup
    workflow = service.autonomous
    mature(); assert workflow.tick(scope)
    original_run = workflow.current(scope)
    old = service.workbench(scope)['vouchers'][0]
    service.validate_draft(scope, voucher_id=old['object_id'], actor_id='alice', expected_version=1)
    save(workflow, scope)
    assert workflow.current(scope)['data']['parent_id'] == original_run['object_id']
    assert service.store.get_object(original_run['object_id'], scope)['status'] == 'ACCEPTED'
    assert not service.workbench(scope)['vouchers']
    with pytest.raises(PreconditionFailed):
        service.validate_draft(scope, voucher_id=old['object_id'], actor_id='alice', expected_version=2)
    workflow.runner = lambda *args: policy_result(base, workflow.review_context(scope))
    mature(); assert workflow.tick(scope)
    current = service.workbench(scope)['vouchers'][0]
    assert current['status'] == 'DRAFT' and 'carried_from' not in current['data']
    service.validate_draft(scope, voucher_id=current['object_id'], actor_id='alice', expected_version=1)
    save(workflow, scope, version=1, note='重新确认相同规则，补充确认来源')
    mature(); assert workflow.tick(scope)
    assert service.workbench(scope)['vouchers'][0]['status'] == 'DRAFT'
    assert service.workbench(scope)['autonomous_workflow']['applied_travel_policy']['version'] == 2
    assert not service.store.list_objects('DeliveryPackage', scope)


@pytest.mark.parametrize('defect', ['old_contract', 'missing_snapshot', 'wrong_version', 'missing_list'])
def test_host_rejects_incomplete_policy_review_even_with_pass_verdict(setup, defect):
    _, service, scope, _, mature, base = setup
    workflow = service.autonomous
    save(workflow, scope)
    result = policy_result(base, workflow.review_context(scope))
    if defect == 'old_contract': result['review_policy_version'] = 4
    if defect == 'missing_snapshot': result['review'].pop('reviewed_travel_policy')
    if defect == 'wrong_version': result['review']['reviewed_travel_policy']['version'] = 99
    if defect == 'missing_list': result['delivery'].pop('travel_policy_applications')
    workflow.runner = lambda *args: result
    mature(); assert not workflow.tick(scope)
    assert workflow.current(scope)['status'] == 'BLOCKED'
    assert not service.store.list_objects('VoucherVersion', scope)


def test_policy_changed_during_analysis_rejects_late_result(setup):
    _, service, scope, _, mature, base = setup
    workflow = service.autonomous
    save(workflow, scope)
    old = workflow.current(scope)
    def changed(*args):
        result = policy_result(base, workflow.review_context(scope))
        save(workflow, scope, version=1, enabled=False, note='分析中停用')
        return result
    workflow.runner = changed
    mature(); assert not workflow.tick(scope)
    assert service.store.get_object(old['object_id'], scope)['status'] == 'STALE'
    assert not service.store.list_objects('VoucherVersion', scope)


def application(delivery, *, kind='TRAVEL', pending=None):
    item = dict(id='travel-001', policy_id='policy', policy_version=1, voucher='001', kind=kind,
                reason='发票、银行差旅备注和历史账内查重有据；按企业默认分类提出本期候选',
                evidence=[delivery['entries'][0]['source']], settlement_match_ids=['m1'],
                manual_reasons=pending or [], confirmed_reasons=[], finding_ids=['gap'] if pending else [])
    delivery['travel_policy_applications'] = [item]
    return item


def context():
    return {'travel_policy':{'id':'policy', 'version':1}, 'statements':[]}


def test_ordinary_travel_ready_only_after_real_gross_matching(settlement):
    root, manifest, delivery, tables = settlement
    item = application(delivery)
    assert travel_policy_errors(delivery, context())
    delivery['bank'][0]['expense'] = '990.00'
    delivery['settlement_matches'][0].update(status='MATCHED', finding_ids=[])
    tables['s']['Bank'][1]['values'][1] = 990.00
    assert not settlement_match_errors(delivery, tables)[0]
    assert not travel_policy_errors(delivery, context())
    item['policy_version'] = 2
    assert any('冻结版本' in e for e in travel_policy_errors(delivery, context()))
    item['policy_version'] = 1
    assert travel_policy_errors(delivery, {})
    item['settlement_match_ids'] = []
    assert travel_policy_errors(delivery, context())


@pytest.mark.parametrize('amount', ['999.00', '1000.00', '1001.00'])
@pytest.mark.parametrize('kind', ['ALLOWANCE', 'LOAN_OFFSET'])
def test_every_allowance_and_loan_requires_specific_human_confirmation(settlement, amount, kind):
    _, _, delivery, _ = settlement
    delivery['entries'][0]['debit'] = amount
    item = application(delivery, kind=kind)
    assert any('人工确认门禁' in e for e in travel_policy_errors(delivery, context()))
    item.update(manual_reasons=[kind], finding_ids=['gap'])
    delivery['findings'][0]['blocks_confirmation'] = True
    assert travel_policy_errors(delivery, context())  # READY cannot hide pending human work.
    delivery['voucher_assessments'][0]['status'] = 'NEEDS_EVIDENCE'
    assert not travel_policy_errors(delivery, context())
    item.update(manual_reasons=[], confirmed_reasons=[{'code':kind,'answer_ids':['answer']}])
    for answer in (
        {'kind':'MATERIALS_COMPLETE'},
        {'kind':'INVOICE_MATCH_SELECTION','affected_vouchers':['001'],'note':''},
        {'kind':'REVIEW_SELECTION','option':{'kind':'DEFER'},'affected_vouchers':['001']},
        {'kind':'FREE_TEXT','affected_vouchers':['other']},
    ):
        assert travel_policy_errors(delivery, {**context(), 'statements':[{'answer_id':'answer', **answer}]})
    answered = {**context(), 'statements':[{'answer_id':'answer','kind':'FREE_TEXT','affected_vouchers':['001']}]}
    assert not travel_policy_errors(delivery, answered)


@pytest.mark.parametrize('code', ['DUPLICATE','EMPLOYEE_SETTLEMENT','PERIOD','AMOUNT_GAP','INVOICE_MISSING'])
def test_real_manual_issues_cannot_be_removed_or_downgraded_to_pass(settlement, code):
    _, _, delivery, _ = settlement
    item = application(delivery, kind='SETTLEMENT', pending=[code])
    delivery['voucher_assessments'][0]['status'] = 'NEEDS_EVIDENCE'
    delivery['findings'][0]['blocks_confirmation'] = True
    assert not travel_policy_errors(delivery, context())
    delivery['findings'].clear()
    assert travel_policy_errors(delivery, context())
    item['finding_ids'] = []
    assert travel_policy_errors(delivery, context())


def test_policy_application_independent_coverage_and_malformed_inputs(settlement):
    _, _, delivery, _ = settlement
    application(delivery, kind='SETTLEMENT')
    review = {'reviewed_travel_policy':{'id':'policy','version':1}, 'reviewed_travel_policy_applications':['travel-001']}
    assert travel_policy_reviewed(delivery, review, context())
    for ids in ([], ['travel-001','travel-001'], ['wrong']):
        assert not travel_policy_reviewed(delivery, {**review, 'reviewed_travel_policy_applications':ids}, context())
    for malformed in (None, {}, [None], [{'id':[]}], [{'id':'incomplete'}]):
        delivery['travel_policy_applications'] = malformed
        assert travel_policy_errors(delivery, context())
        assert not travel_policy_reviewed(delivery, review, context())


def test_policy_revision_keeps_original_and_unknown_references_rejected(settlement):
    _, _, delivery, _ = settlement
    application(delivery, kind='MEAL')
    original = deepcopy(delivery['entries'])
    revised = deepcopy(original)
    revised[0].update(code='660205', name='管理费用—业务招待费')
    delivery['revisions'] = [dict(voucher='001', entries=revised, answer_ids=[], policy_application_ids=['travel-001'],
                                 reason='餐费按本企业口径提出分类候选，保留原账')]
    assert not review_loop_errors(delivery, context())
    assert delivery['entries'] == original
    delivery['revisions'][0]['policy_application_ids'] = ['forged']
    assert review_loop_errors(delivery, context())
    delivery['revisions'][0]['policy_application_ids'] = ['travel-001']
    assert review_loop_errors(delivery, {})


def test_frozen_checker_enforces_policy_source_and_gap_gates(settlement, setup):
    root, manifest, delivery, _ = settlement
    _, service, _, _, _, _ = setup
    item = application(delivery, kind='SETTLEMENT', pending=['AMOUNT_GAP'])
    delivery['voucher_assessments'][0]['status'] = 'NEEDS_EVIDENCE'
    delivery['findings'][0]['blocks_confirmation'] = True
    workspace, _ = prepare(root/'policy-run', manifest, {'s':root/'source.xlsx'}, context(), service.autonomous.settings)
    namespace = {}
    exec((workspace/'tools/checker.py').read_text(), namespace)
    assert namespace['validate'](workspace, manifest, delivery, {}, context())['passed']
    item['evidence'] = [{'source_id':'another-company','sheet':'Bank','row':2}]
    checked = namespace['validate'](workspace, manifest, delivery, {}, context())
    assert not checked['passed'] and any('本轮原件' in e for e in checked['errors'])
    item['evidence'] = [delivery['entries'][0]['source']]
    delivery['settlement_matches'][0]['status'] = 'MATCHED'
    assert not namespace['validate'](workspace, manifest, delivery, {}, context())['passed']
