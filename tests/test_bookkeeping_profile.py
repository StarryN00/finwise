from copy import deepcopy
from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient

from app.bookkeeping_profile import (profile_reference, snapshot, profile_contract,
    bookkeeping_profile_errors, bookkeeping_profile_reviewed)
from app.ontology.contracts import Scope
from app.ontology.errors import PreconditionFailed
from app.review_loop import review_loop_errors
from app.autonomous_runtime import prepare, CONTRACT_V2
from test_autonomous_workflow import setup


def save(client, scope, mode='ORIGINAL', version=0, **kwargs):
    return client.post('/api/v1/autonomous/bookkeeping-profile', json={
        'scope': scope.model_dump(), 'mode': mode, 'expected_version': version, **kwargs})


def test_default_simple_switch_preserves_history_and_invalidates_review(setup):
    app, service, scope, source, mature, result = setup
    w = service.autonomous
    assert w.bookkeeping_profile(scope)['id'] == 'AGENCY_SIMPLE'
    assert w.bookkeeping_profile(scope)['cost_ratio'] is None
    mature(); assert w.tick(scope)
    old = w.current(scope)
    voucher = w.project(scope)['vouchers'][0]
    service.validate_draft(scope, voucher_id=voucher['object_id'], actor_id='alice', expected_version=1)
    response = save(TestClient(app), scope)
    assert response.status_code == 200, response.text
    assert response.json()['changed']
    assert w.current(scope)['data']['parent_id'] == old['object_id']
    assert service.store.get_object(old['object_id'], scope)['status'] == 'ACCEPTED'
    assert not w.project(scope)['vouchers']
    with pytest.raises(PreconditionFailed):
        w.validate_voucher(scope, voucher, 'alice', 1)
    mature(); assert w.tick(scope)
    new = w.project(scope)['vouchers'][0]
    assert new['status'] == 'DRAFT'
    assert new['data']['bookkeeping_profile']['id'] == 'ORIGINAL'
    assert new['data']['review_basis'] != voucher['data']['review_basis']
    response = save(TestClient(app), scope, 'AGENCY_SIMPLE', 1)
    assert response.status_code == 200
    mature(); assert w.tick(scope)
    assert w.project(scope)['vouchers'][0]['status'] == 'DRAFT'


def test_profile_reuse_is_per_ledger_and_cost_ratio_is_explicit(setup):
    app, service, scope, _, _, _ = setup
    w=service.autonomous; w.cancel(scope, 'alice', 'operator')
    client=TestClient(app)
    assert save(client,scope,'AGENCY_SIMPLE',cost_ratio='0.9').status_code == 409
    response=save(client,scope,'AGENCY_SIMPLE',cost_ratio='0.9',source_note='财务公司已确认本企业90%')
    assert response.status_code==200,response.text
    profile=response.json()['profile']
    assert profile['cost_ratio']=='0.9' and 'cost_ratio' in profile['rule_ids']
    next_month=Scope(**{**scope.model_dump(),'accounting_period_id':'2026-04','baseline_id':'april'})
    assert w.bookkeeping_profile(next_month)==profile
    for key in ['tenant_id','organization_id','legal_entity_id','ledger_id']:
        other=Scope(**{**scope.model_dump(),key:'other'})
        assert w.bookkeeping_profile(other)['selection_version']==0
        assert w.bookkeeping_profile(other)['cost_ratio'] is None
    before=w.inputs(scope)[0]
    w.cancel(scope,'alice','operator')
    assert save(client,scope,'AGENCY_SIMPLE',1,cost_ratio=None).status_code==200
    assert w.inputs(scope)[0]!=before
    assert 'cost_ratio' not in w.bookkeeping_profile(scope)['rule_ids']


def test_permissions_conflicts_active_guard_and_noop(setup):
    app,service,scope,_,mature,_=setup;w=service.autonomous;client=TestClient(app)
    body={'scope':scope.model_dump(),'mode':'ORIGINAL','expected_version':0}
    assert client.post('/api/v1/autonomous/bookkeeping-profile',json=body,headers={'X-Role':'viewer'}).status_code==403
    assert save(client,scope).status_code==409  # Currently queued.
    assert w.bookkeeping_profile(scope)['selection_version']==0
    for bad in [{'mode':'CUSTOM'},{'expected_version':True},{'cost_ratio':0.9},{'cost_ratio':'NaN'},{'source_note':'x','cost_ratio':'1.2'}]:
        assert client.post('/api/v1/autonomous/bookkeeping-profile',json={**body,**bad}).status_code==422
    mature(); assert w.tick(scope)
    assert save(client,scope).status_code==200
    assert save(client,scope).status_code==409
    current=w.current(scope)
    assert save(client,scope,version=1).json()['changed'] is False
    assert w.current(scope)['object_id']==current['object_id']


@pytest.mark.parametrize('tamper', ['delivery','assessment','review','version'])
def test_wrong_or_missing_profile_never_admitted_even_with_pass_review(setup,tamper):
    _,service,scope,_,mature,result=setup;w=service.autonomous
    def wrong(*args):
        r=result()
        if tamper=='delivery':r['delivery'].pop('bookkeeping_profile')
        if tamper=='assessment':r['delivery']['voucher_assessments'][0].pop('bookkeeping_profile')
        if tamper=='review':r['review'].pop('reviewed_bookkeeping_profile')
        if tamper=='version':r['review']['reviewed_bookkeeping_profile']={**r['review']['reviewed_bookkeeping_profile'],'version':99}
        return r
    w.runner=wrong;mature();assert not w.tick(scope)
    assert not service.store.list_objects('VoucherVersion',scope)


def test_profile_contract_is_frozen_for_both_executor_and_checker(setup,tmp_path):
    _,service,scope,_,_,result=setup;w=service.autonomous
    context=w.review_context(scope)
    root,_=prepare(tmp_path/'sandbox',{'sources':[]},{},context,w.settings)
    contract=(root/'CONTRACT.md').read_text()
    assert contract.startswith(CONTRACT_V2)
    assert '简易代账新增规则' in contract and '付款方买货' in contract
    assert '12月' in contract and '比例' in contract
    assert json.loads((root/'context.json').read_text())['bookkeeping_profile']==context['bookkeeping_profile']
    ns={};exec((root/'tools/checker.py').read_text(),ns)
    delivery=result()['delivery']
    assert ns['bookkeeping_profile_errors'](delivery,context)==[]
    delivery['bookkeeping_profile']['selection_version']=99
    assert ns['bookkeeping_profile_errors'](delivery,context)
    original=snapshot({'version':1,'data':{'mode':'ORIGINAL','cost_ratio':'0.9'}})
    assert '### 简易代账新增规则' not in profile_contract(original)
    assert original['rule_ids']==[]


def test_only_selected_supported_rules_authorize_proposed_revisions(setup):
    _,service,scope,_,_,result=setup
    context=service.autonomous.review_context(scope);d=result()['delivery']
    d['revisions']=[{'voucher':'候选001','reason':'按已选规则重分科目','answer_ids':[],
                     'profile_rule_ids':['software_service'],'entries':deepcopy(d['entries'])}]
    assert review_loop_errors(d,context)==[]
    d['revisions'][0]['profile_rule_ids']=['cost_ratio']
    assert review_loop_errors(d,context)  # No company ratio was confirmed.
    d['revisions'][0]['profile_rule_ids']=['software_service']
    context['bookkeeping_profile']=snapshot({'version':1,'data':{'mode':'ORIGINAL'}})
    assert review_loop_errors(d,context)


def test_profile_only_edit_during_execution_rejects_late_result(setup):
    _,service,scope,_,mature,result=setup;w=service.autonomous
    def late(*args):
        r=result();w.cancel(scope,'alice','operator')
        w.save_bookkeeping_profile(scope,'alice','operator',mode='ORIGINAL',expected_version=0)
        return r
    w.runner=late;mature();assert not w.tick(scope)
    assert w.current(scope)['data']['bookkeeping_profile']['id']=='ORIGINAL'
    assert not service.store.list_objects('VoucherVersion',scope)


def test_authenticated_save_enforces_scope_csrf_and_server_identity(tmp_path, scope):
    from pathlib import Path
    from app.auth import create_user, grant_scope
    from app.config import Settings
    from app.main import create_app
    from test_scope_provisioning import login
    settings=Settings(root=Path(__file__).resolve().parents[1], database_path=tmp_path/'secured.db',
                      storage_path=tmp_path/'sources', require_auth=True, autonomous_enabled=True)
    app=create_app(settings);service=app.state.service
    own=Scope(**scope);other=Scope(**{**scope,'legal_entity_id':'other-enterprise'})
    service.create_scope(own);service.create_scope(other)
    create_user(app.state.database,'alice','correct-horse-battery','accountant')
    grant_scope(app.state.database,'alice',own)
    client,headers=login(app,'alice','correct-horse-battery')
    body={'scope':other.model_dump(),'mode':'ORIGINAL','expected_version':0}
    assert client.post('/api/v1/autonomous/bookkeeping-profile',json=body,headers=headers).status_code==403
    body['scope']=own.model_dump()
    assert client.post('/api/v1/autonomous/bookkeeping-profile',json=body).status_code==403
    r=client.post('/api/v1/autonomous/bookkeeping-profile',json=body,headers={**headers,'X-Actor-Id':'impostor'})
    assert r.status_code==200,r.text
    assert r.json()['status']=='SAVED' and r.json()['run_id'] is None
    assert r.json()['profile']['saved_by']=='alice'
    assert service.autonomous.bookkeeping_profile(other)['selection_version']==0


@pytest.mark.parametrize('period_status',['CLOSED','ARCHIVED','LOCKED'])
def test_later_month_switch_preserves_closed_month_results(setup,period_status):
    _,service,scope,_,mature,_=setup;w=service.autonomous
    mature();assert w.tick(scope)
    old=w.current(scope);vouchers=w.project(scope)['vouchers']
    period=service.store.get_object(service._period_object_id(scope),scope)
    # Fixture transition only; production close prerequisites remain unchanged.
    service.store.revise_object(period['object_id'],period['version'],scope,period['data'],status=period_status,created_by='test')
    later=Scope(**{**scope.model_dump(),'accounting_period_id':'2026-04','baseline_id':'april'})
    service.create_scope(later)
    w.save_bookkeeping_profile(later,'alice','operator',mode='ORIGINAL',expected_version=0)
    assert not w.tick(scope)
    assert w.current(scope)==old
    view=w.project(scope)
    assert view['vouchers']==vouchers
    assert view['autonomous_workflow']['applied_bookkeeping_profile']['id']=='AGENCY_SIMPLE'
    assert not view['autonomous_workflow']['can_reassess']
    # Legacy runs predate the selector; they must never be labelled as simple mode.
    legacy_data={k:v for k,v in old['data'].items() if k!='bookkeeping_profile'}
    service.store.revise_object(old['object_id'],old['version'],scope,legacy_data,status='ACCEPTED',created_by='test')
    assert w.project(scope)['autonomous_workflow']['applied_bookkeeping_profile']['id']=='ORIGINAL'
    with pytest.raises(PreconditionFailed):
        w.save_bookkeeping_profile(scope,'alice','operator',mode='AGENCY_SIMPLE',expected_version=1)


@pytest.mark.parametrize('old_version,new_version', [(2,3),(3,4)])
def test_trade_settlement_rule_upgrade_preserves_history(setup, monkeypatch, old_version, new_version):
    from app import bookkeeping_profile
    _, service, scope, source, mature, _ = setup
    workflow = service.autonomous
    monkeypatch.setattr(bookkeeping_profile, 'PROFILE_VERSION', old_version)
    workflow.enqueue(scope, 'alice')
    mature()
    assert workflow.tick(scope)
    old_run = deepcopy(workflow.current(scope))
    voucher = deepcopy(workflow.project(scope)['vouchers'][0])
    source_before = deepcopy(service.store.get_object(source['object_id'], scope))
    monkeypatch.setattr(bookkeeping_profile, 'PROFILE_VERSION', new_version)
    assert workflow.inputs(scope)[0] != old_run['data']['fingerprint']
    assert workflow.project(scope)['autonomous_workflow']['stale']
    with pytest.raises(PreconditionFailed):
        workflow.validate_voucher(scope, voucher, 'alice', voucher['version'])
    assert service.store.get_object(old_run['object_id'], scope) == old_run
    assert service.store.get_object(voucher['object_id'], scope) == voucher
    assert service.store.get_object(source['object_id'], scope) == source_before
