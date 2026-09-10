from copy import deepcopy
import pytest
from app.ontology.contracts import Scope
from conftest import command
from test_tabular_ingestion import uploaded, parse, xlsx_fixture, INVOICE_HEADERS
from test_material_review import view


def setup_invoices(client, scope):
    a = uploaded(client, scope, xlsx_fixture([('发票', [INVOICE_HEADERS,
        ['RED-1', '2026-03-01', '-100', '-13', '13%', '甲'],
        ['ZERO-1', '2026-03-02', '0', '0', '13%', '甲'],
        ['RED-OLD', '2026-02-02', '-100', '-13', '13%', '甲'],
        ['POSITIVE', '2026-03-03', '100', '13', '13%', '甲']])]))
    e = parse(client, scope, a).json()['effect']
    return e['artifact'], e['facts']


def confirm_amount(client, scope, f, key='confirm-amount', **extra):
    token = next((t['input_token'] for t in view(client, scope)['material_review']['tasks']
                  if t['kind']=='INVOICE_AMOUNT' and f['object_id'] in t['record_ids']), 'stale')
    return command(client, scope, 'confirm_invoice_amount', f['object_id'], f['version'], key,
                   {'input_token':token, 'reason':'已核对原始金额，确认为退货冲红。', **extra})


def test_confirm_removes_only_matching_warning_and_keeps_financial_gates(client, scope):
    a, facts = setup_invoices(client, scope); before = view(client, scope)
    result = confirm_amount(client, scope, facts[0]); assert result.status_code==200, result.text
    saved=result.json()['effect']['object']; after=view(client, scope)
    row=next(r for r in after['material_review']['records'] if r['object_id']==facts[0]['object_id'])
    assert row['state']=='ISSUE_CONFIRMED' and not row['issues']
    assert after['material_review']['counts']['invoice_amount_confirmed']==1
    assert after['material_review']['counts']['source_verified']==0
    assert saved['data']['confirmed_by']=='alice' and saved['data']['binding']['sha256']==a['data']['sha256']
    for k in ['data_readiness','baseline','baseline_validation','vouchers','groups']: assert after[k]==before[k]
    assert client.app.state.store.get_object(facts[0]['object_id'], Scope(**scope))==facts[0]
    assert client.app.state.store.get_object(a['object_id'], Scope(**scope))==a
    assert confirm_amount(client, scope, facts[1], 'confirm-zero').status_code==200
    assert confirm_amount(client, scope, facts[2], 'confirm-old').status_code==200
    row=next(r for r in view(client,scope)['material_review']['records'] if r['object_id']==facts[2]['object_id'])
    assert row['state']=='PERIOD_EXCEPTION' and row['issues']
    assert command(client,scope,'revoke_invoice_amount',saved['object_id'],saved['version'],'revoke-amount',{'reason':'重新核对'}).status_code==200
    assert any(facts[0]['object_id'] in t['record_ids'] for t in view(client,scope)['material_review']['tasks'] if t['kind']=='INVOICE_AMOUNT')


@pytest.mark.parametrize('extra', [{'reason':''},{'amount':'100'},{'confirmed_by':'other'},{'input_token':'old'}])
def test_invalid_payload(client,scope,extra):
    _,facts=setup_invoices(client,scope)
    assert confirm_amount(client,scope,facts[0],**extra).status_code==409


def test_source_change_invalidation_and_permissions(client,scope):
    a,facts=setup_invoices(client,scope);s=client.app.state.store;typed=Scope(**scope)
    assert confirm_amount(client,scope,facts[3],'reject-positive').status_code==409
    result=confirm_amount(client,scope,facts[0]);assert result.status_code==200
    saved=result.json()['effect']['object']
    assert command(client,scope,'revoke_invoice_amount',saved['object_id'],1,'no-permission',{},role='reviewer').status_code==403
    s.revise_object(a['object_id'],a['version'],typed,deepcopy(a['data']),status='ACTIVE',created_by='test')
    after=view(client,scope)
    assert after['material_review']['counts']['invoice_amount_confirmed']==0
    assert after['invoice_amount_review']['confirmations'][0]['stale']


def test_idempotency_token_scope_and_closed_period(client,scope):
    a,facts=setup_invoices(client,scope)
    t=next(t for t in view(client,scope)['material_review']['tasks'] if t['kind']=='INVOICE_AMOUNT')
    payload={'input_token':t['input_token'],'reason':'已核对负数原件与业务原因'}
    f=facts[0]
    first=command(client,scope,'confirm_invoice_amount',f['object_id'],f['version'],'repeat-invoice',payload)
    assert first.status_code==200
    assert command(client,scope,'confirm_invoice_amount',f['object_id'],f['version'],'repeat-invoice',payload).json()['idempotent']
    assert command(client,scope,'confirm_invoice_amount',f['object_id'],f['version'],'new-key-old-input',payload).status_code==409
    other={**scope,'legal_entity_id':'foreign'}
    assert command(client,other,'confirm_invoice_amount',f['object_id'],f['version'],'foreign-invoice',payload).status_code in {403,404,409}
    s=client.app.state.service;typed=Scope(**scope);period=s.store.list_objects('AccountingPeriod',typed)[0]
    s.store.revise_object(period['object_id'],period['version'],typed,period['data'],status='CLOSED',created_by='test')
    assert confirm_amount(client,scope,facts[1],'closed-period-invoice').status_code==409


def test_tamper_and_replay_mismatch_rejected(client,scope):
    a,facts=setup_invoices(client,scope);s=client.app.state.store;typed=Scope(**scope)
    d=deepcopy(facts[0]['data']);d['normalized_value']['invoice_total']='-114.00'
    f=s.revise_object(facts[0]['object_id'],facts[0]['version'],typed,d,status=facts[0]['status'],created_by='test')
    assert confirm_amount(client,scope,f,'mismatch-invoice').status_code==409
    p=s.database.settings.storage_path/a['data']['storage_path'];p.write_bytes(b'tampered fixture')
    assert confirm_amount(client,scope,facts[1],'tampered-invoice').status_code==409


def test_defer_then_confirm_does_not_count_as_source_verification(client,scope):
    a,facts=setup_invoices(client,scope)
    task=next(t for t in view(client,scope)['material_review']['tasks'] if t['kind']=='INVOICE_AMOUNT')
    assert command(client,scope,'defer_material_issue',a['object_id'],a['version'],'defer-invoice',{'task_id':task['id'],'reason':'尚待客户答复'}).status_code==200
    assert confirm_amount(client,scope,facts[0]).status_code==200
    m=view(client,scope)['material_review'];c=m['counts']
    assert c['deferred']==0 and c['source_verified']==0 and c['invoice_amount_confirmed']==1
    assert c['system_checked']+c['needs_review']+c['period_exceptions']+c['business_confirmed']+c['issue_confirmed']==c['records']
    assert client.app.state.store.list_objects('MaterialIssueResponse',Scope(**scope))
