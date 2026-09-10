from copy import deepcopy
from app.ontology.contracts import Scope
from conftest import command
from test_tabular_ingestion import uploaded, parse, xlsx_fixture


def setup(client,scope,rows=None):
    rows=rows or [['2026-04-02 09:26:44','0','15000','客户','TX-1'],['2026-04-02 09:28:45','1000','0','供应商','TX-2']]
    a=uploaded(client,scope,xlsx_fixture([('流水',[
        ['交易时间','支出金额','收入金额','对方户名','交易流水号'],*rows])]))
    result=parse(client,scope,a,kind='bank_statement',bank_account_ref='synthetic-account-a',key='parse-bank-'+scope['accounting_period_id']).json()['effect']
    return result['artifact'],result['facts']


def view(client,scope):return client.post('/api/v1/workbench',json={'scope':scope}).json()


def assign(client,scope,a,ids=None,extra=None,key='assign-bank-1',role='accountant'):
    t=next(t for t in view(client,scope)['material_review']['tasks'] if t.get('bank_period'))
    info=t['bank_period']
    return command(client,scope,'confirm_bank_period',a['object_id'],a['version'],key,
        {'task_id':t['id'],'input_token':info['input_token'],'record_ids':ids or info['record_ids'],
         'target_period':info['target_period'],**(extra or {})},role=role)


def target(client,scope):
    s={**scope,'accounting_period_id':'2026-04','baseline_id':'baseline-april'}
    client.app.state.service.create_scope(Scope(**s));return s


def accept(client,s,key='accept-bank-1'):
    wb=view(client,s);i=wb['bank_periods']['incoming'][0];p=wb['period']
    return command(client,s,'accept_bank_period',p['object_id'],p['version'],key,
        {k:i[k] for k in ('assignment_id','assignment_version','input_token')})


def test_assignment_preserves_facts_and_counts_other_period(client,scope):
    a,f=setup(client,scope);s=client.app.state.service;before=deepcopy(f)
    wb=view(client,scope);t=next(t for t in wb['material_review']['tasks'] if t.get('bank_period'))
    assert t['descriptor']['options'][0]['id']=='confirm_bank_period'
    assert [s['fields'] for s in t['descriptor']['options'][0]['steps']]==[['records'],['reason']]
    r=assign(client,scope,a);assert r.status_code==200,r.text
    assert len(r.json()['effect']['objects'])==2
    wb=view(client,scope);c=wb['material_review']['counts']
    assert c['period_exceptions']==0
    assert wb['bank_periods']['counts']['confirmed_other_period']==2
    assert all(r['period_assignment'] for r in wb['material_review']['records'])
    assert c['system_checked']+c['needs_review']+c['period_exceptions']+c['other_period']==c['records']
    assert c['source_verified']==c['accounting_usable']==0
    assert all(x['handoff_status']=='WAITING_PERIOD' for x in wb['bank_periods']['outgoing'])
    assert [s.store.get_object(x['object_id'],Scope(**scope)) for x in f]==before


def test_assignment_subset_and_version_guard(client,scope):
    a,f=setup(client,scope)
    assert assign(client,scope,a,[f[0]['object_id']]).status_code==200
    wb=view(client,scope);assert wb['material_review']['counts']['period_exceptions']==1
    t=next(t for t in wb['material_review']['tasks'] if t.get('bank_period'))
    assert t['record_ids']==[f[1]['object_id']]
    assert assign(client,scope,a,[f[1]['object_id']],key='bank-second').status_code==200


def test_wrong_month_role_injected_values_and_duplicates_rejected(client,scope):
    a,f=setup(client,scope)
    assert assign(client,scope,a,extra={'target_period':'2026-05'}).status_code==409
    assert assign(client,scope,a,extra={'amount':0},key='bank-inject').status_code==409
    assert assign(client,scope,a,role='viewer',key='bank-viewer').status_code==403
    assert assign(client,scope,a,[f[0]['object_id'],f[0]['object_id']],key='bank-duplicate').status_code==409


def test_intake_reference_no_fact_copy_and_revoke_dependencies(client,scope):
    a,f=setup(client,scope);assert assign(client,scope,a).status_code==200
    dst=target(client,scope);wb=view(client,dst)
    assert len(wb['bank_periods']['incoming'])==2
    i=wb['bank_periods']['incoming'][0];p=wb['period']
    body={k:i[k] for k in ('assignment_id','assignment_version','input_token')}
    r=command(client,dst,'accept_bank_period',p['object_id'],p['version'],'accept-bank-1',body);assert r.status_code==200,r.text
    intake=r.json()['effect']['object']
    assert command(client,dst,'accept_bank_period',p['object_id'],p['version'],'accept-bank-1',body).json()['idempotent']
    wb=view(client,dst);assert wb['bank_periods']['counts']['accepted']==1
    assert wb['counts']['facts']==0 and wb['material_review']['counts']['accounting_usable']==0
    x=view(client,scope)['bank_periods']['outgoing'][0]
    assert command(client,scope,'revoke_bank_period',x['object_id'],x['version'],'revoke-source-block').status_code==409
    assert command(client,dst,'revoke_bank_period_intake',intake['object_id'],intake['version'],'revoke-intake').status_code==200
    assert command(client,scope,'revoke_bank_period',x['object_id'],x['version'],'revoke-source-ok').status_code==200
    assert view(client,scope)['material_review']['counts']['period_exceptions']==1


def test_source_changed_invalidates_intake_without_rewriting(client,scope):
    a,f=setup(client,scope);assert assign(client,scope,a).status_code==200
    dst=target(client,scope);assert accept(client,dst).status_code==200
    svc=client.app.state.service
    changed=deepcopy(f[0]['data'])
    changed['normalized_value']['income']='999999.00'
    svc.store.revise_object(f[0]['object_id'],f[0]['version'],Scope(**scope),changed,status=f[0]['status'],created_by='test')
    assert view(client,dst)['bank_periods']['counts']['accepted']==0
    row=next(x for x in view(client,dst)['bank_periods']['incoming'] if x['binding']['fact_id']==f[0]['object_id'])
    assert row['status']=='STALE'
    assert row['values']==f[0]['data']['normalized_value']
    assert view(client,scope)['material_review']['counts']['period_exceptions']==1


def test_duplicate_source_and_ambiguous_same_amount(client,scope):
    a,f=setup(client,scope);assert assign(client,scope,a).status_code==200
    dst=target(client,scope);setup(client,dst)
    rows=view(client,dst)['bank_periods']['incoming']
    assert all(x['status']=='DUPLICATE' for x in rows)
    assert accept(client,dst).status_code==409


def test_foreign_scope_and_closed_target_rejected(client,scope):
    a,f=setup(client,scope);assert assign(client,scope,a).status_code==200
    dst=target(client,scope);foreign={**dst,'legal_entity_id':'other'}
    svc=client.app.state.service;svc.create_scope(Scope(**foreign))
    assert not view(client,foreign)['bank_periods']['incoming']
    p=view(client,dst)['period'];svc.store.revise_object(p['object_id'],p['version'],Scope(**dst),p['data'],status='CLOSED',created_by='test')
    assert accept(client,dst).status_code==409


def test_other_issues_retained_and_source_hash_guard(client,scope):
    a,f=setup(client,scope,[['2026-04-02','not-money','0','客户','TX']])
    assert assign(client,scope,a).status_code==200
    wb=view(client,scope);assert wb['material_review']['counts']['needs_review']==1
    assert any('金额格式无效' in i for i in wb['material_review']['records'][0]['issues'])
    svc=client.app.state.service;path=svc.store.database.settings.storage_path/a['data']['storage_path']
    path.write_bytes(b'fixture invalidated')
    assert not view(client,scope)['bank_periods']['outgoing'][0]['valid']


def test_reading_never_writes_or_calls_gateway(client,scope,monkeypatch):
    a,f=setup(client,scope);svc=client.app.state.service
    monkeypatch.setattr(svc.gateway,'complete',lambda *a,**k: (_ for _ in ()).throw(AssertionError('read called model')))
    before=svc.store.list_objects(None,Scope(**scope),latest_only=False)
    assert view(client,scope)==view(client,scope)
    assert before==svc.store.list_objects(None,Scope(**scope),latest_only=False)


def test_intake_deduplicates_distinct_assignments_for_same_source(client,scope):
    a,f=setup(client,scope);assert assign(client,scope,a).status_code==200
    dst=target(client,scope);assert accept(client,dst).status_code==200
    svc=client.app.state.service
    original=svc.store.list_objects('BankPeriodAssignment',Scope(**scope))[0]
    duplicate=svc.store.create_initial_object('BankPeriodAssignment',Scope(**scope),
        original['data'],status='CONFIRMED',created_by='fixture')
    item=next(x for x in view(client,dst)['bank_periods']['incoming'] if x['assignment_id']==duplicate['object_id'])
    assert item['status']=='DUPLICATE'
    p=view(client,dst)['period']
    result=command(client,dst,'accept_bank_period',p['object_id'],p['version'],'duplicate-reference',
        {k:item[k] for k in ('assignment_id','assignment_version','input_token')})
    assert result.status_code==409


def test_intake_requires_real_target_scope_grant(client,scope):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.auth import create_user,grant_scope
    a,_=setup(client,scope);assert assign(client,scope,a).status_code==200
    dst=target(client,scope);svc=client.app.state.service
    settings=replace(svc.store.database.settings,require_auth=True)
    app=create_app(settings)
    create_user(app.state.database,'source-only','SourceOnlyTest!2026','accountant')
    grant_scope(app.state.database,'source-only',Scope(**scope))
    secured=TestClient(app)
    login=secured.post('/api/v1/auth/login',json={'username':'source-only','password':'SourceOnlyTest!2026'})
    secured.headers['X-CSRF-Token']=login.json()['csrf_token']
    wb=view(client,dst);i=wb['bank_periods']['incoming'][0];p=wb['period']
    body={'scope':dst,'action':'accept_bank_period','target_id':p['object_id'],'target_version':p['version'],
        'idempotency_key':'secured-intake','payload':{k:i[k] for k in ('assignment_id','assignment_version','input_token')}}
    assert secured.post('/api/v1/commands',json=body,headers={'X-Role':'admin'}).status_code==403
    grant_scope(app.state.database,'source-only',Scope(**dst))
    r=secured.post('/api/v1/commands',json=body)
    assert r.status_code==200,r.text
    assert r.json()['effect']['object']['data']['accepted_by']=='source-only'


def test_stored_date_cannot_replace_actual_original_cell(client,scope):
    a,f=setup(client,scope);svc=client.app.state.service
    data=deepcopy(f[0]['data']);data['normalized_value'].update(transaction_date='2026-05-02',period='2026-05')
    data['field_sources']['transaction_date']['original_value']='2026-05-02'
    svc.store.revise_object(f[0]['object_id'],f[0]['version'],Scope(**scope),data,status='PERIOD_EXCEPTION',created_by='test')
    assert not svc.bank_periods.target_month(Scope(**scope),svc.store.get_object(f[0]['object_id'],Scope(**scope)),a)


def test_date_reference_cannot_borrow_another_transaction_row(client,scope):
    a,f=setup(client,scope);svc=client.app.state.service
    data=deepcopy(f[0]['data'])
    data['field_sources']['transaction_date']=deepcopy(f[1]['data']['field_sources']['transaction_date'])
    altered={**f[0],'data':data}
    assert svc.bank_periods.target_month(Scope(**scope),f[0],a)=='2026-04'
    assert svc.bank_periods.target_month(Scope(**scope),altered,a) is None


def test_same_month_other_baseline_cannot_intake_twice(client,scope):
    a,f=setup(client,scope);assert assign(client,scope,a).status_code==200
    dst=target(client,scope);assert accept(client,dst).status_code==200
    second={**dst,'baseline_id':'different-baseline'}
    assignment=view(client,scope)['bank_periods']['outgoing'][0]
    # Scope creation itself disallows a second baseline for one month. Also
    # guard the transfer resolver against legacy/alternate-scope use.
    assert client.app.state.service.bank_periods.duplicate_status(Scope(**second),assignment)=='ACCEPTED_ELSEWHERE'


def test_ambiguous_date_amount_is_not_silently_deduplicated(client,scope):
    a,f=setup(client,scope);assert assign(client,scope,a).status_code==200
    dst=target(client,scope)
    setup(client,dst,[['2026-04-02 11:00:00','0','15000','不同客户','DIFFERENT-ID']])
    assert view(client,dst)['bank_periods']['incoming'][0]['status']=='AMBIGUOUS'
    assert accept(client,dst).status_code==409


def test_intake_downstream_dependency_prevents_revoke(client,scope):
    a,f=setup(client,scope);assert assign(client,scope,a).status_code==200
    dst=target(client,scope);r=accept(client,dst);intake=r.json()['effect']['object']
    svc=client.app.state.service
    svc.store.create_initial_object('BusinessEvent',Scope(**dst),{'source_ids':[intake['object_id']]},status='CANDIDATE',created_by='test')
    result=command(client,dst,'revoke_bank_period_intake',intake['object_id'],intake['version'],'dependency-revoke')
    assert result.status_code==409


def test_no_invisible_page_group_assignment(client,scope):
    a,f=setup(client,scope,[[f'2026-04-0{i+1}','0',str(10+i),'客户',f'TX-{i}'] for i in range(6)])
    assert assign(client,scope,a,[f[0]['object_id'],f[5]['object_id']]).status_code==409
