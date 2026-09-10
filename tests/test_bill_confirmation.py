from copy import deepcopy
import pytest
from app.ontology.contracts import Scope
from conftest import command
from test_tabular_ingestion import uploaded, xlsx_fixture
from test_material_review import view


def setup_bills(client, scope):
    a = uploaded(client, scope, xlsx_fixture([('票据', [
        ['票据（包）号', '子票区间', '出票日', '到期日', '票据（包）金额', '票据状态'],
        ['PACK-1', '1,2', '20260127', '20260727', '20265', '已收票'],
        ['PACK-1', '3,4', '20260127', '20260727', '15000', '已收票']])]))
    res = command(client, scope, 'parse_artifact', a['object_id'], a['version'], 'parse-bills', {'document_kind': 'electronic_acceptance'})
    assert res.status_code == 200, res.text
    return res.json()['effect']['artifact'], res.json()['effect']['facts']


def confirm_bill(client, scope, fact, key='confirm-bill', **overrides):
    if '_bill_token' not in fact:
        fact['_bill_token'] = next((t['input_token'] for t in view(client,scope).get('material_review',{}).get('tasks',[]) if t['kind']=='BILL' and fact['object_id'] in t['record_ids']), 'stale')
    payload = dict(business_kind='RECEIVED', business_period=scope['accounting_period_id'],
                   input_token=fact['_bill_token'],
                   business_date='', original_receipt_period='', account_candidate_id='',
                   account_name='应收票据', account_code='', reason='已向客户核实，本期收到货款票据', evidence_ids=[])
    payload.update(overrides)
    return command(client, scope, 'confirm_bill_business', fact['object_id'], fact['version'], key, payload)


def test_confirmation_preserves_original_and_financial_gates(client, scope):
    a, facts = setup_bills(client, scope); before = view(client, scope)
    result = confirm_bill(client, scope, facts[0]); assert result.status_code == 200, result.text
    saved = result.json()['effect']['object']; d = saved['data']
    assert d['confirmed_by'] == 'alice' and d['binding']['sub_range'] == '1,2'
    assert d['business_date'] == '' and d['date_precision'] == 'MONTH'
    assert d['account_status'] == 'PROPOSED' and saved['status'] == 'CONFIRMED'
    after = view(client, scope)
    assert after['bill_review']['confirmed_count'] == 1
    rows = {r['object_id']: r for r in after['material_review']['records']}
    assert not any('票据清单未列' in i for i in rows[facts[0]['object_id']]['issues'])
    assert any('票据清单未列' in i for i in rows[facts[1]['object_id']]['issues'])
    assert after['material_review']['counts']['source_verified'] == 0
    for k in ['baseline', 'baseline_validation', 'vouchers', 'groups', 'data_readiness']:
        assert after[k] == before[k]
    s = client.app.state.service
    assert s.store.get_object(facts[0]['object_id'], Scope(**scope)) == {k:v for k,v in facts[0].items() if k!='_bill_token'}
    assert s.store.get_object(a['object_id'], Scope(**scope)) == a
    assert confirm_bill(client, scope, facts[0]).json()['idempotent']
    assert confirm_bill(client, scope, facts[0], 'duplicate-new-key').status_code == 409
    revoked = command(client, scope, 'revoke_bill_business', saved['object_id'], saved['version'], 'revoke-bill', {'reason':'需重新核对'})
    assert revoked.status_code == 200
    assert view(client, scope)['bill_review']['confirmed_count'] == 0


@pytest.mark.parametrize('change', [dict(business_period='2026-02'), dict(business_date='2026-03-99'),
    dict(business_date='2026-02-01'), dict(business_date='2026-03-01', business_kind='HELD', original_receipt_period='2026-02'),
    dict(business_kind='HELD', original_receipt_period='2026-03'), dict(business_kind='HELD', original_receipt_period='2025-12'),
    dict(reason=''), dict(amount='1.00'), dict(confirmed_by='mallory'), dict(account_candidate_id='foreign')])
def test_invalid_manual_input_rejected(client, scope, change):
    _, facts = setup_bills(client, scope)
    assert confirm_bill(client, scope, facts[0], **change).status_code == 409


def test_held_and_other_do_not_create_current_receipt(client, scope):
    _, facts = setup_bills(client, scope)
    result = confirm_bill(client, scope, facts[0], business_kind='HELD', original_receipt_period='2026-02')
    assert result.status_code == 200, result.text
    assert result.json()['effect']['object']['data']['current_receipt'] is False
    result = confirm_bill(client, scope, facts[1], key='other-bill', business_kind='OTHER')
    assert result.status_code == 200
    assert result.json()['effect']['object']['status'] == 'OPINION'
    assert view(client, scope)['bill_review']['confirmed_count'] == 1
    assert any(t['kind']=='BILL' and facts[1]['object_id'] in t['record_ids'] for t in view(client,scope)['material_review']['tasks'])


def test_current_baseline_candidates_and_candidate_revision_invalidate(client,scope):
    from test_baseline_safety import baseline_input, confirm
    s=client.app.state.service;typed=Scope(**scope)
    payload=baseline_input(s,typed);assert confirm(client,scope,payload).status_code==200
    _,facts=setup_bills(client,scope)
    before=view(client,scope);candidate=before['bill_review']['candidates'][0]
    assert candidate['status']=='BASELINE'
    result=confirm_bill(client,scope,facts[0],account_candidate_id=candidate['id'],account_name='',account_code='')
    assert result.status_code==200,result.text
    after=view(client,scope);counts=after['material_review']['counts']
    assert counts['business_confirmed']==1 and counts['source_verified']==0 and counts['accounting_usable']==0
    assert counts['system_checked']+counts['needs_review']+counts['period_exceptions']+counts['business_confirmed']==counts['records']
    assert before['data_readiness']==after['data_readiness']
    baseline=after['baseline'];s.store.revise_object(baseline['object_id'],baseline['version'],typed,baseline['data'],status='CONFIRMED',created_by='fixture')
    assert view(client,scope)['bill_review']['confirmed_count']==0
    assert confirm_bill(client,scope,facts[1],key='stale-account',account_candidate_id=candidate['id'],account_name='',account_code='').status_code==409


def test_other_anomalies_and_each_pending_account_remain_individual(client,scope):
    _,facts=setup_bills(client,scope)
    assert confirm_bill(client,scope,facts[0]).status_code==200
    assert confirm_bill(client,scope,facts[1],key='bill-second').status_code==200
    tasks=view(client,scope)['material_review']['tasks']
    accounts=[t for t in tasks if t['kind']=='BILL_ACCOUNT']
    assert len(accounts)==2 and all(len(t['record_ids'])==1 for t in accounts)


def test_artifact_revision_token_and_closed_period_rejected(client,scope):
    a,facts=setup_bills(client,scope);s=client.app.state.service;typed=Scope(**scope)
    facts[0]['_bill_token']=next(t['input_token'] for t in view(client,scope)['material_review']['tasks'] if facts[0]['object_id'] in t['record_ids'])
    s.store.revise_object(a['object_id'],a['version'],typed,a['data'],status=a['status'],created_by='fixture')
    assert confirm_bill(client,scope,facts[0]).status_code==409
    period=view(client,scope)['period'];s.store.revise_object(period['object_id'],period['version'],typed,period['data'],status='CLOSED',created_by='fixture')
    assert confirm_bill(client,scope,facts[1],key='bill-closed').status_code==409


def test_evidence_invalidation_and_unrelated_issues_are_not_erased(client,scope):
    a,facts=setup_bills(client,scope);s=client.app.state.service;typed=Scope(**scope)
    f=facts[0];d=deepcopy(f['data']);d['extraction_issues'].append('amount：金额仍需核对')
    f=s.store.revise_object(f['object_id'],f['version'],typed,d,status=f['status'],created_by='fixture')
    evidence=uploaded(client,scope,xlsx_fixture([('依据',[['说明'],['合成依据']])]))
    result=confirm_bill(client,scope,f,evidence_ids=[evidence['object_id']]);assert result.status_code==200,result.text
    row=next(r for r in view(client,scope)['material_review']['records'] if r['object_id']==f['object_id'])
    assert any('金额仍需核对' in i for i in row['issues'])
    assert row['state']=='NEEDS_REVIEW'
    s.store.revise_object(evidence['object_id'],evidence['version'],typed,evidence['data'],status='ARCHIVED',created_by='fixture')
    assert view(client,scope)['bill_review']['confirmed_count']==0


def test_deferred_bill_can_later_be_confirmed_without_attachment(client,scope):
    _,facts=setup_bills(client,scope);task=next(t for t in view(client,scope)['material_review']['tasks'] if t['kind']=='BILL')
    assert command(client,scope,'defer_material_issue',task['artifact_id'],task['artifact_version'],'bill-defer',{'task_id':task['id'],'reason':'暂未取得信息'}).status_code==200
    assert confirm_bill(client,scope,facts[0]).status_code==200
    assert view(client,scope)['material_review']['counts']['deferred']==0
    assert len(client.app.state.service.store.list_objects('MaterialIssueResponse',Scope(**scope)))==1


def test_binding_invalidates_and_scope_role_checks(client, scope):
    a, facts = setup_bills(client, scope); assert confirm_bill(client, scope, facts[0]).status_code == 200
    s=client.app.state.service; typed=Scope(**scope)
    s.store.revise_object(facts[0]['object_id'],facts[0]['version'],typed,{**facts[0]['data'],'changed':True},status=facts[0]['status'],created_by='fixture')
    assert view(client,scope)['bill_review']['confirmed_count']==0
    assert confirm_bill(client,scope,facts[0],key='old-version').status_code==409
    other={**scope,'legal_entity_id':'other'};s.create_scope(Scope(**other))
    assert confirm_bill(client,other,facts[1],key='other-scope').status_code==403
    assert command(client,scope,'confirm_bill_business',facts[1]['object_id'],facts[1]['version'],'viewer',{},role='viewer').status_code==403
    path=s.store.database.settings.storage_path/a['data']['storage_path'];path.write_bytes(b'changed isolated original')
    assert confirm_bill(client,scope,facts[1],key='bad-hash').status_code==409
