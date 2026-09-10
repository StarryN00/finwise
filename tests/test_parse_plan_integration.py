"""API integration uses only synthetic workbooks and pytest temporary storage."""
from copy import deepcopy
import json

import pytest

from app.ontology.contracts import Scope
from app.ontology.errors import PreconditionFailed, ScopeViolation
from app.ontology.gateway import GatewayFailure, GatewayResult, DeepSeekProvider
from app.parse_plan import VERSION, EXECUTOR_VERSION
from conftest import command
from test_tabular_ingestion import uploaded, xlsx_fixture, INVOICE_HEADERS
from test_material_review import verify, view
from test_gateway import FakeResponse, settings_for
from test_payroll_mapping_replay import applied


def invoice(period='2026-03', tail=None):
    rows=[INVOICE_HEADERS,['TEST-001',period+'-01',100,13,'13%','合成供应商']]
    if tail:rows.append(tail)
    return xlsx_fixture([('发票样本',rows)])


def proposal():
    return {'schema_version':VERSION,'outcome':'PLAN','sheets':[
        {'sheet_index':0,'role':'DATA','header_row':1,
         'fields':{'invoice_no':'A','invoice_date':'B','net_amount':'C','tax':'D','tax_rate':'E','seller_name':'F'},
         'reference_rows':[]}]}


@pytest.fixture()
def source(client,scope):
    return uploaded(client,scope,invoice())


def preview(client,scope,artifact,plan=None,key='plan-preview'):
    response=command(client,scope,'preview_parse_plan',artifact['object_id'],artifact['version'],key,
        {'proposal':plan or proposal(),'document_kind':'purchase_invoices'})
    assert response.status_code==200,response.text
    return response.json()['effect']['object']


def apply(client,scope,job,key='plan-apply',**changes):
    payload={'proposal':job['data']['proposal'],'preview_token':job['data'].get('preview_token'), 'plan_confirmed':True}
    payload.update(changes)
    return command(client,scope,'apply_parse_plan',job['object_id'],job['version'],key,payload)


def ask(client,scope,source,key='structure-request',**changes):
    body={'scope':scope,'stage':'STRUCTURE_PLAN','artifact_id':source['object_id'],
          'artifact_version':source['version'],'document_kind':'purchase_invoices','idempotency_key':key}
    body.update(changes)
    return client.post('/api/v1/agent/suggestion',json=body,headers={'X-Actor-Id':'alice','X-Role':'accountant'})


def fake_result(output=None):
    return GatewayResult(output if output is not None else proposal(),'fixture','synthetic',True,
        'structure-plan-prompt-v1','input','output',1,{},schema_version=VERSION)


def test_inspect_is_audited_without_financial_object_writes(client,app,scope,source):
    before=app.state.store.list_objects('SourceArtifact',Scope(**scope))
    response=command(client,scope,'inspect_parse_plan',source['object_id'],source['version'],'inspect-plan',
                     {'document_kind':'purchase_invoices'})
    assert response.status_code==200,response.text
    effect=response.json()['effect']
    assert effect['artifact']['sha256']==source['data']['sha256']
    assert effect['sheets'][0]['rows'][1]['values'][0]=='TEST-001'
    assert effect['proposal']['schema_version']==VERSION
    assert not app.state.store.list_objects('ParsePlan',Scope(**scope))
    assert app.state.store.list_objects('SourceArtifact',Scope(**scope))==before
    assert app.state.store.find_command('inspect-plan')['status']=='SUCCEEDED'


def test_manual_preview_apply_replay_verify_and_idempotency(client,app,scope,source,monkeypatch):
    def forbidden(*args,**kwargs):pytest.fail('No built-in parser or model is allowed')
    monkeypatch.setattr(app.state.service.gateway,'complete',forbidden)
    monkeypatch.setattr('app.ontology.service.extract_workbook',forbidden)
    monkeypatch.setattr('app.tabular.extract_workbook',forbidden)
    job=preview(client,scope,source)
    assert not app.state.store.list_objects('FactRecord',Scope(**scope))
    assert job['data']['preview']['apply_ready']
    response=apply(client,scope,job);assert response.status_code==200,response.text
    effect=response.json()['effect'];artifact=effect['artifact'];fact=effect['facts'][0]
    assert apply(client,scope,job).json()['idempotent']
    ref=artifact['data']['plan_ref']
    assert ref['plan_id']==job['object_id'] and ref['plan_version']==effect['object']['version']
    assert 'payroll_mapping_id' not in artifact['data']
    assert fact['data']['plan_id']==job['object_id']
    result=app.state.service.parse_plans.replay(Scope(**scope),artifact)
    assert result['records'][0]['field_sources']==fact['data']['field_sources']
    checked=verify(client,scope,artifact,fact,'plan-source-verify')
    assert checked.status_code==200,checked.text
    assert view(client,scope)['material_review']['counts']['source_verified']==1
    assert view(client,scope)['material_review']['counts']['accounting_usable']==0
    assert view(client,scope)['parse_plans'][0]['status']=='APPLIED'


def test_payroll_material_verification_uses_mapping_replay(client,scope,applied):
    service,typed,effect=applied
    response=verify(client,scope,effect['artifact'],effect['facts'][0],'payroll-source-verify')
    assert response.status_code==200,response.text


def test_gateway_request_has_no_transaction_and_is_idempotent(client,app,scope,source,monkeypatch):
    calls=[]
    def complete(bound_scope,**kwargs):
        assert app.state.database._transaction_connection.get() is None
        # A second connection can acquire the writer lock during inference.
        with app.state.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE');connection.rollback()
        calls.append(kwargs)
        safe=json.dumps(kwargs['sanitized_input'],ensure_ascii=False)
        for secret in ('TEST-001','合成供应商','2026-03-01','发票样本'):
            assert secret not in safe
        assert kwargs['stage']=='STRUCTURE_PLAN'
        return fake_result()
    monkeypatch.setattr(app.state.service.gateway,'complete',complete)
    response=ask(client,scope,source);assert response.status_code==200,response.text
    job=response.json()['object'];assert job['status']=='REVIEW'
    assert not job['data'].get('preview_token')
    assert ask(client,scope,source).json()['idempotent'] and len(calls)==1
    assert ask(client,scope,source,artifact_version=9).status_code==409
    assert apply(client,scope,job).status_code==409
    response=command(client,scope,'preview_parse_plan',job['object_id'],job['version'],'ai-preview',{'proposal':job['data']['proposal']})
    assert response.status_code==200,response.text
    job=response.json()['effect']['object'];assert job['data']['origin']=='AI'
    assert apply(client,scope,job,'ai-apply').status_code==200


@pytest.mark.parametrize('output',[
    {'amount':123},
    {**proposal(),'amount':123},
    {**proposal(),'sheets':[{**proposal()['sheets'][0],'header_row':900}]},
])
def test_invalid_model_output_fails_without_fallback(client,app,scope,source,monkeypatch,output):
    monkeypatch.setattr(app.state.service.gateway,'complete',lambda *a,**k:fake_result(output))
    response=ask(client,scope,source)
    assert response.status_code==200 and response.json()['object']['status']=='FAILED'
    assert not app.state.store.list_objects('FactRecord',Scope(**scope))


def test_abstention_and_transport_failure_are_persisted(client,app,scope,source,monkeypatch):
    monkeypatch.setattr(app.state.service.gateway,'complete',lambda *a,**k:fake_result({'schema_version':VERSION,'outcome':'ABSTAIN','sheets':[]}))
    assert ask(client,scope,source).json()['object']['status']=='NEEDS_INPUT'
    def fail(*a,**k):raise GatewayFailure('SENSITIVE_PROVIDER_BODY','PROVIDER_UNAVAILABLE')
    monkeypatch.setattr(app.state.service.gateway,'complete',fail)
    response=ask(client,scope,source,'retry')
    assert response.json()['object']['status']=='FAILED'
    assert 'SENSITIVE_PROVIDER_BODY' not in response.text
    assert ask(client,scope,source,'retry').json()['idempotent']


@pytest.mark.parametrize('change',['source','period','permission'])
def test_late_result_cannot_apply_after_boundary_changes(client,app,scope,source,monkeypatch,change):
    service=app.state.service;typed=Scope(**scope)
    def complete(*a,**k):
        if change=='source':
            app.state.store.revise_object(source['object_id'],source['version'],typed,source['data'],status='ARCHIVED',created_by='test')
        elif change=='period':
            period=service.workbench(typed)['period']
            app.state.store.revise_object(period['object_id'],period['version'],typed,period['data'],status='CLOSED',created_by='test')
        else:
            from app.ontology.errors import PermissionDenied
            def revoked(*a,**k):raise PermissionDenied('revoked')
            monkeypatch.setattr(service.parse_plans,'authorized',revoked)
        return fake_result()
    monkeypatch.setattr(service.gateway,'complete',complete)
    response=ask(client,scope,source)
    assert response.status_code==200 and response.json()['object']['status']=='FAILED'
    assert not app.state.store.list_objects('FactRecord',typed)


@pytest.mark.parametrize('changes',[
    {'plan_confirmed':False},{'preview_token':'bad'},
    {'proposal':{**proposal(),'amount':100}},
])
def test_apply_requires_exact_preview_and_confirmation(client,app,scope,source,changes):
    job=preview(client,scope,source)
    assert apply(client,scope,job,**changes).status_code==409
    assert not app.state.store.list_objects('FactRecord',Scope(**scope))


@pytest.mark.parametrize('role',['viewer','reviewer'])
def test_unauthorized_roles_cannot_preview_or_request(client,scope,source,role):
    response=command(client,scope,'preview_parse_plan',source['object_id'],source['version'],'forbidden-preview',
        {'proposal':proposal(),'document_kind':'purchase_invoices'},role=role)
    assert response.status_code==403
    body={'scope':scope,'stage':'STRUCTURE_PLAN','artifact_id':source['object_id'],
          'artifact_version':source['version'],'document_kind':'purchase_invoices','idempotency_key':'forbidden-request'}
    assert client.post('/api/v1/agent/suggestion',json=body,headers={'X-Role':role}).status_code==403


def test_request_refuses_client_supplied_model_values(client,scope,source):
    assert ask(client,scope,source,model_output=proposal()).status_code==422


def test_new_preview_invalidates_prior_version_and_idempotency_payload(client,scope,source):
    job=preview(client,scope,source)
    response=command(client,scope,'preview_parse_plan',job['object_id'],job['version'],'preview-new',{'proposal':proposal()})
    assert response.status_code==200
    assert apply(client,scope,job).status_code==409
    assert command(client,scope,'preview_parse_plan',job['object_id'],job['version'],'preview-new',{'proposal':{}}).status_code==409


def test_bound_plan_survives_parser_upgrade_and_ordinary_parse_is_blocked(client,app,scope,source,monkeypatch):
    effect=apply(client,scope,preview(client,scope,source)).json()['effect']
    monkeypatch.setattr('app.ontology.service.PARSER_VERSION','future-parser')
    response=command(client,scope,'parse_artifact',effect['artifact']['object_id'],effect['artifact']['version'],'no-flatten',{'document_kind':'purchase_invoices'})
    assert response.status_code==409
    assert app.state.service.parse_plans.replay(Scope(**scope),effect['artifact'])['records']


@pytest.mark.parametrize('dimension',list(Scope.model_fields))
def test_plan_replay_and_commands_cannot_cross_scope(client,app,scope,source,dimension):
    job=preview(client,scope,source)
    effect=apply(client,scope,job).json()['effect']
    other={**scope,dimension:'other'}
    assert command(client,other,'apply_parse_plan',job['object_id'],job['version'],'other-apply',{}).status_code==403
    with pytest.raises(PreconditionFailed):app.state.service.parse_plans.replay(Scope(**other),effect['artifact'])


@pytest.mark.parametrize('changes',[{'sha256':'0'*64},{'executor_version':'obsolete'}, {'proposal':{}}, {'applied_artifact_version':99}])
def test_replay_rejects_invalidated_binding(client,app,scope,source,changes):
    effect=apply(client,scope,preview(client,scope,source)).json()['effect'];job=effect['object'];typed=Scope(**scope)
    app.state.store.revise_object(job['object_id'],job['version'],typed,{**job['data'],**changes},status='APPLIED',created_by='test')
    with pytest.raises(PreconditionFailed):app.state.service.parse_plans.replay(typed,effect['artifact'])


def test_reapplying_plan_preserves_fact_identity_and_invalidates_verification(client,app,scope,source):
    first=apply(client,scope,preview(client,scope,source)).json()['effect']
    assert verify(client,scope,first['artifact'],first['facts'][0]).status_code==200
    second=preview(client,scope,first['artifact'],key='repreview')
    assert second['data']['impact']['invalidated_confirmation_count']==1
    response=apply(client,scope,second,'plan-reapply');assert response.status_code==200,response.text
    fact=response.json()['effect']['facts'][0]
    assert fact['object_id']==first['facts'][0]['object_id'] and fact['version']>first['facts'][0]['version']
    assert view(client,scope)['material_review']['counts']['source_verified']==0


def test_reuse_rereads_new_period_and_still_requires_preview(client,app,scope,source,monkeypatch):
    apply(client,scope,preview(client,scope,source))
    other={**scope,'accounting_period_id':'2026-04','baseline_id':'baseline-april'}
    new=uploaded(client,other,invoice('2026-04'))
    def forbidden(*a,**k):pytest.fail('Confirmed format reuse needs no model')
    monkeypatch.setattr(app.state.service.gateway,'complete',forbidden)
    response=ask(client,other,new,'reuse');assert response.status_code==200,response.text
    job=response.json()['object'];assert job['data']['origin']=='REUSED_FORMAT'
    assert job['data']['preview']['records'][0]['normalized_value']['invoice_date']=='2026-04-01'
    assert apply(client,other,job,'reuse-apply').status_code==409


def test_absolute_reference_rows_are_not_reused(client,app,scope,monkeypatch):
    source=uploaded(client,scope,invoice(tail=['备注']))
    plan=proposal();plan['sheets'][0]['reference_rows']=[{'row':3,'role':'NOTE'}]
    assert apply(client,scope,preview(client,scope,source,plan)).status_code==200
    other={**scope,'accounting_period_id':'2026-04','baseline_id':'baseline-april'}
    new=uploaded(client,other,invoice('2026-04',tail=['备注']))
    calls=[]
    def complete(*a,**k):calls.append(1);return fake_result(plan)
    monkeypatch.setattr(app.state.service.gateway,'complete',complete)
    assert ask(client,other,new).json()['object']['data']['origin']=='AI'
    assert calls==[1]


def test_gateway_uses_structure_schema_and_prompt(tmp_path):
    seen={}
    def opener(request,timeout):
        seen.update(json.loads(request.data))
        return FakeResponse({'choices':[{'message':{'content':json.dumps(proposal())}}]})
    result=DeepSeekProvider(settings_for(tmp_path),opener=opener).complete(stage='STRUCTURE_PLAN',request_payload={},input_hash='test')
    assert result.schema_version==VERSION and result.prompt_version=='structure-plan-prompt-v1'
    assert '不输出金额' in seen['messages'][0]['content']
    assert seen['temperature']==0
    assert seen['max_tokens']==4096
    assert 'INVOICE_HEADERS' in seen['messages'][0]['content']


@pytest.mark.parametrize('budget,expected',[(1200,4096),(6000,6000),(16000,8192)])
def test_gateway_structure_budget_and_truncated_output_rejected(tmp_path,budget,expected):
    seen={}
    def opener(request,timeout):
        seen.update(json.loads(request.data))
        # Valid-looking JSON must still be rejected when transport says truncated.
        return FakeResponse({'choices':[{'finish_reason':'length','message':{'content':json.dumps(proposal())}}]})
    provider=DeepSeekProvider(settings_for(tmp_path,agent_max_tokens=budget),opener=opener)
    with pytest.raises(GatewayFailure) as error:
        provider.complete(stage='STRUCTURE_PLAN',request_payload={},input_hash='test')
    assert error.value.code=='STRUCTURE_PLAN_TRUNCATED'
    assert seen['max_tokens']==expected


def test_inspect_supports_local_windows_beyond_packet_samples(client,scope):
    source=uploaded(client,scope,xlsx_fixture([('长表',[[f'标题{n}'] for n in range(110)])]))
    response=command(client,scope,'inspect_parse_plan',source['object_id'],source['version'],'inspect-window',
        {'document_kind':'purchase_invoices','row_start':50,'page_size':3})
    assert response.status_code==200,response.text
    sheet=response.json()['effect']['sheets'][0]
    assert [r['row'] for r in sheet['rows']]==[50,51,52] and sheet['total_rows']==110
    assert command(client,scope,'inspect_parse_plan',source['object_id'],source['version'],'bad-window',
        {'document_kind':'purchase_invoices','row_start':0,'page_size':101}).status_code==409


def test_impact_lists_confirmations_and_transitive_dependents(client,app,scope,source):
    effect=apply(client,scope,preview(client,scope,source)).json()['effect']
    artifact=effect['artifact'];fact=effect['facts'][0];store=app.state.store;typed=Scope(**scope)
    confirmation=store.create_initial_object('BillBusinessConfirmation',typed,
        {'binding':{'artifact_id':artifact['object_id'],'fact_id':fact['object_id']}},status='CONFIRMED',created_by='test')
    group=store.create_initial_object('ProcessingGroup',typed,{'member_fact_ids':[fact['object_id']]},status='CONFIRMED',created_by='test')
    voucher=store.create_initial_object('VoucherVersion',typed,{'group_id':group['object_id']},status='DRAFT',created_by='test')
    job=preview(client,scope,artifact,key='impact-preview')
    impact=job['data']['impact']
    assert impact['invalidated_confirmation_count']==2
    assert impact['dependent_check_count']==3
    assert {d['object_id'] for d in impact['dependencies']}=={confirmation['object_id'],group['object_id'],voucher['object_id']}
    assert impact['dependency_counts']['BillBusinessConfirmation']==1
    store.revise_object(confirmation['object_id'],confirmation['version'],typed,confirmation['data'],status='REVOKED',created_by='test')
    assert apply(client,scope,job,'impact-changed').status_code==409


def test_bank_plan_account_binding_replays_same_rows_then_verifies(client,app,scope):
    from test_bank_accounts import bank_file
    source=uploaded(client,scope,bank_file(),filename='农业银行.xlsx')
    plan={'schema_version':VERSION,'outcome':'PLAN','sheets':[
        {'sheet_index':0,'role':'DATA','header_row':2,'fields':{
            'transaction_date':'A','income':'B','expense':'C','balance':'D',
            'counterparty_account':'E','counterparty':'F'},'reference_rows':[]}]}
    response=command(client,scope,'preview_parse_plan',source['object_id'],source['version'],'bank-plan-preview',
        {'proposal':plan,'document_kind':'bank_statement'})
    assert response.status_code==200,response.text
    response=apply(client,scope,response.json()['effect']['object'],'bank-plan-apply')
    assert response.status_code==200,response.text
    effect=response.json()['effect'];a=effect['artifact'];svc=app.state.service;typed=Scope(**scope)
    candidate=svc.bank_accounts.view(typed)['statements'][0]
    payload={'token':candidate['token'],'ownership_confirmed':True,
        'new_account':{k:candidate['identity'][k] for k in ('account_number','holder','bank_name','currency')}}
    response=command(client,scope,'confirm_statement_account',a['object_id'],a['version'],'bank-plan-account',payload)
    assert response.status_code==200,response.text
    bound=response.json()['effect']
    assert bound['artifact']['data']['plan_ref']['plan_id']==a['data']['plan_ref']['plan_id']
    assert bound['artifact']['data']['plan_ref']['plan_version']>a['data']['plan_ref']['plan_version']
    assert [f['object_id'] for f in bound['facts']]==[f['object_id'] for f in effect['facts']]
    checked=verify(client,scope,bound['artifact'],bound['facts'][0],'bank-plan-verify')
    assert checked.status_code==200,checked.text


def test_source_guard_never_sends_model_or_applies(client,app,scope,monkeypatch):
    source=uploaded(client,scope,invoice(tail=['金额单位：万元']))
    def forbidden(*a,**k):pytest.fail('Guarded input must not leave the host')
    monkeypatch.setattr(app.state.service.gateway,'complete',forbidden)
    assert ask(client,scope,source).status_code==422
    job=preview(client,scope,source)
    assert not job['data']['preview']['apply_ready']
    assert apply(client,scope,job).status_code==409


def test_running_request_retry_does_not_call_model_twice(client,app,scope,source,monkeypatch):
    calls=[]
    def complete(*a,**k):
        calls.append(1)
        nested=ask(client,scope,source)
        assert nested.json()['idempotent'] and nested.json()['object']['status']=='RUNNING'
        return fake_result()
    monkeypatch.setattr(app.state.service.gateway,'complete',complete)
    assert ask(client,scope,source).json()['object']['status']=='REVIEW'
    assert calls==[1]


def test_expired_request_cannot_be_resurrected_by_late_completion(client,app,scope,source,monkeypatch):
    def complete(*a,**k):
        job=app.state.store.list_objects('ParsePlan',Scope(**scope))[0]
        monkeypatch.setattr('app.parse_plans.time.time',lambda:job['data']['expires_at']+1)
        assert ask(client,scope,source).json()['object']['status']=='FAILED'
        return fake_result()
    monkeypatch.setattr(app.state.service.gateway,'complete',complete)
    response=ask(client,scope,source)
    assert response.json()['object']['status']=='FAILED'
    assert 'proposal' not in response.json()['object']['data']


def test_apply_refuses_source_hash_change(client,app,scope,source,monkeypatch):
    job=preview(client,scope,source)
    path=app.state.database.settings.storage_path/source['data']['storage_path']
    read=type(path).read_bytes
    monkeypatch.setattr(type(path),'read_bytes',lambda p:b'tampered' if p==path else read(p))
    assert apply(client,scope,job).status_code==409
    assert not app.state.store.list_objects('FactRecord',Scope(**scope))


def test_ordinary_payroll_parse_cannot_flatten_mapping_after_upgrade(applied,monkeypatch):
    from app.ontology.service import OntologyService
    mapping,scope,effect=applied;artifact=effect['artifact']
    monkeypatch.setattr('app.ontology.service.PARSER_VERSION','future-parser')
    with pytest.raises(PreconditionFailed,match='工资字段'):
        OntologyService.parse_artifact(mapping.service,scope,artifact_id=artifact['object_id'],
            actor_id='alice',expected_version=artifact['version'],payload={'document_kind':'payroll'})


def test_failed_full_reconciliation_cannot_create_facts(client,app,scope):
    from test_tabular_ingestion import parse
    raw=xlsx_fixture([('流水',[
        ['交易日期','收入金额','支出金额'],
        ['2026-03-01',10,0],['2026-03-02',0,3],
        ['总收入笔数','总收入金额','总支出笔数','总支出金额'],[1,99,1,3]])])
    source=uploaded(client,scope,raw,filename='流水.xlsx')
    response=parse(client,scope,source,'bank_statement')
    assert response.status_code==200,response.text
    effect=response.json()['effect']
    assert effect['artifact']['data']['parse_status']=='RECONCILIATION_FAILED'
    assert effect['artifact']['data']['parse_checks']['overall']=='REVIEW'
    assert not effect['facts'] and not app.state.store.list_objects('FactRecord',Scope(**scope))
    tasks=view(client,scope)['material_review']['tasks']
    assert len(tasks)==1 and tasks[0]['kind']=='PARSE' and tasks[0]['action']=='parse'
    assert '对账差异' in tasks[0]['title']


@pytest.mark.parametrize('dimension',['tenant_id','organization_id','legal_entity_id','ledger_id'])
def test_confirmed_format_is_never_reused_across_company_scope(client,app,scope,source,monkeypatch,dimension):
    assert apply(client,scope,preview(client,scope,source)).status_code==200
    other={**scope,dimension:'other-company'}
    new=uploaded(client,other,invoice())
    calls=[]
    def complete(*a,**k):calls.append(1);return fake_result()
    monkeypatch.setattr(app.state.service.gateway,'complete',complete)
    response=ask(client,other,new)
    assert response.json()['object']['data']['origin']=='AI' and calls==[1]


@pytest.mark.parametrize('layout',['single_amount_bank','boc-text-v1'])
def test_existing_special_layout_cannot_be_overwritten_via_plan(client,app,scope,source,layout):
    typed=Scope(**scope)
    source=app.state.store.revise_object(source['object_id'],source['version'],typed,
        {**source['data'],'parse_sheets':[{'layout':layout}]},status='ACTIVE',created_by='test')
    assert command(client,scope,'inspect_parse_plan',source['object_id'],source['version'],'special-inspect',
        {'document_kind':'purchase_invoices'}).status_code==409
    assert ask(client,scope,source).status_code==409


def test_single_amount_bank_is_not_forced_into_dual_columns(client,scope):
    raw=xlsx_fixture([('单金额流水',[
        ['交易时间','交易类型','交易金额','余额'],['2026-03-01','转入',100,100]])])
    source=uploaded(client,scope,raw,filename='银行.xlsx')
    response=command(client,scope,'inspect_parse_plan',source['object_id'],source['version'],'single-inspect',{'document_kind':'bank_statement'})
    assert response.status_code==409 and '专用解析' in response.text


@pytest.mark.parametrize('failure,expected',[
    ('missing_required','REQUIRED_FIELDS'),
    ('duplicate_column','DUPLICATE_COLUMN'),('missing_sheet','SHEET_COVERAGE'),
])
def test_safe_failed_proposal_retained_with_replayable_diagnostic(client,app,scope,source,monkeypatch,failure,expected):
    plan=proposal()
    if failure=='missing_required':del plan['sheets'][0]['fields']['tax']
    elif failure=='duplicate_column':plan['sheets'][0]['fields']['tax']='C'
    else:plan['sheets']=[]
    monkeypatch.setattr(app.state.service.gateway,'complete',lambda *a,**k:fake_result(plan))
    response=ask(client,scope,source)
    job=response.json()['object']
    assert job['status']=='FAILED' and job['data']['proposal']==plan
    assert job['data']['validation_stage']=='EXECUTION'
    assert job['data']['gateway']['error_code']=='STRUCTURE_PLAN_'+expected
    assert not job['data'].get('preview_token') and not job['data'].get('preview')
    assert apply(client,scope,job).status_code==409
    # An operator can correct the retained anchors without another model call.
    corrected=command(client,scope,'preview_parse_plan',job['object_id'],job['version'],'diagnostic-preview',{'proposal':proposal()})
    assert corrected.status_code==200,corrected.text
    data=corrected.json()['effect']['object']['data']
    assert data['origin']=='HUMAN' and data['preview']['apply_ready']
    assert 'validation_error_code' not in data


@pytest.mark.parametrize('failure',['schema','unsafe_anchor','unobserved','unexpected_exception'])
def test_diagnostic_never_exposes_arbitrary_model_or_exception_text(client,app,scope,source,monkeypatch,failure):
    marker='SECRET_MODEL_OR_EXCEPTION_TEXT'
    plan=proposal()
    if failure=='schema':plan['secret']=marker
    elif failure=='unsafe_anchor':plan['sheets'][0]['fields']['invoice_no']=marker
    elif failure=='unobserved':plan['sheets'][0]['header_row']=999
    else:
        def fail(*a,**k):raise ValueError(marker)
        monkeypatch.setattr('app.parse_plans.execute',fail)
    monkeypatch.setattr(app.state.service.gateway,'complete',lambda *a,**k:fake_result(plan))
    response=ask(client,scope,source)
    data=response.json()['object']['data']
    assert marker not in response.text
    expected={'schema':'SCHEMA','unsafe_anchor':'ANCHORS','unobserved':'OBSERVATION','unexpected_exception':'EXECUTION'}[failure]
    assert data['validation_stage']==expected
    assert data['validation_error_code']=='STRUCTURE_PLAN_'+expected+'_REJECTED'
    assert ('proposal' in data)==(failure in {'unobserved','unexpected_exception'})


def test_reference_sheet_with_data_fields_is_rejected_by_schema(client,app,scope,source,monkeypatch):
    plan=proposal();plan['sheets'][0]['role']='REFERENCE'
    monkeypatch.setattr(app.state.service.gateway,'complete',lambda *a,**k:fake_result(plan))
    job=ask(client,scope,source).json()['object']
    assert job['status']=='FAILED' and job['data']['validation_stage']=='SCHEMA'
    assert 'proposal' not in job['data']
