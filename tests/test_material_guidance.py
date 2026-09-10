import json
from copy import deepcopy

import pytest

from app.material_guidance import SCHEMA, PROMPT
from app.ontology.contracts import Scope
from app.ontology.gateway import GatewayResult, GatewayFailure, DeepSeekProvider
from app.ontology.store import digest
from test_invoice_amount_review import setup_invoices
from test_material_review import view
from test_gateway import FakeResponse, settings_for
from test_access_control import secured, sign_in


def request_for(client, scope):
    setup_invoices(client, scope)
    t = next(t for t in view(client, scope)['material_review']['tasks'] if t['kind']=='INVOICE_AMOUNT')
    return {'scope': scope, 'stage':'MATERIAL_GUIDANCE', 'task_id':t['id'],
            'descriptor_hash':t['descriptor']['fingerprint'], 'request_id':'request-0001'}


def output(**changes):
    return dict({'option_id':'confirm_invoice_amount','reason':'建议核对金额符号及业务原因后确认，尚未处理。',
                 'uncertainties':['需要用户核对真实业务原因'], 'prefill':{}, 'confidence':.9}, **changes)


def install(client, monkeypatch, value=None, fail=None, callback=None):
    calls=[]
    def complete(scope, *, stage, sanitized_input):
        calls.append((scope, stage, sanitized_input))
        if callback:callback()
        if fail:raise fail
        return GatewayResult(output=value if value is not None else output(), provider='fixture',
                             model_version='fixture-model',mock=True,prompt_version=PROMPT,
                             input_hash=digest(sanitized_input),output_hash=digest(value),latency_ms=1,
                             usage={'total_tokens':3},schema_version=SCHEMA)
    monkeypatch.setattr(client.app.state.service.gateway,'complete',complete)
    return calls


def post(client, body, role='accountant'):
    return client.post('/api/v1/agent/suggestion',json=body,headers={'X-Actor-Id':'alice','X-Role':role})


def test_guidance_only_creates_audited_suggestion_and_is_idempotent(client, scope, monkeypatch):
    body=request_for(client,scope);before=view(client,scope);calls=install(client,monkeypatch)
    result=post(client,body);assert result.status_code==200,result.text
    assert result.json()['status']=='PROPOSED' and result.json()['metadata']['mock'] is True
    assert post(client,body).json()==result.json() and len(calls)==1
    after=view(client,scope)
    for key in ('material_review','data_readiness','baseline','groups','vouchers','deliveries','artifacts'):
        assert after[key]==before[key]
    run=after['material_guidance'][0]
    assert run['created_by']=='alice' and run['status']=='SUCCEEDED'
    assert run['data']['binding']['artifact']['sha256']
    assert run['data']['gateway']['prompt_version']==PROMPT
    assert run['data']['response']['suggestion']['prefill']=={}
    encoded=json.dumps(calls[0][2],ensure_ascii=False)
    for prohibited in ('RED-1','甲','legal-a','ledger-a','113','2026-03-01','.xlsx'):
        assert prohibited not in encoded
    assert calls[0][1]=='MATERIAL_GUIDANCE'
    assert calls[0][2]['records'][0]['issue_fields']==['invoice_total']


@pytest.mark.parametrize('changes',[
    {'option_id':'generate_draft'}, {'option_id':'confirm_baseline'}, {'prefill':{'business_period':'2026-03'}},
    {'confidence':2}, {'reason':''}, {'extra':'invented'}, {'uncertainties':['x'*501]},
])
def test_invalid_suggestion_is_failed_not_executable(client,scope,monkeypatch,changes):
    body=request_for(client,scope);install(client,monkeypatch,output(**changes))
    r=post(client,body);assert r.status_code==200
    assert r.json()['status']=='FAILED' and r.json()['suggestion'] is None
    assert view(client,scope)['material_guidance'][0]['status']=='FAILED'
    assert not view(client,scope)['vouchers']


@pytest.mark.parametrize('changes',[{'option_id':None},{'confidence':.3}])
def test_uncertainty_returns_human_path_without_option(client,scope,monkeypatch,changes):
    body=request_for(client,scope);install(client,monkeypatch,output(**changes))
    result=post(client,body).json()
    assert result['status']=='NEEDS_HUMAN' and result['suggestion']['option_id'] is None
    assert view(client,scope)['material_review']['counts']['issue_confirmed']==0


def test_failure_redacts_provider_body_and_retry_key_preserves_receipt(client,scope,monkeypatch):
    body=request_for(client,scope);calls=install(client,monkeypatch,fail=GatewayFailure('secret-key or original names','PROVIDER_UNAVAILABLE'))
    result=post(client,body).json();assert result['status']=='FAILED'
    assert result['metadata']['mock'] is None
    assert 'secret-key' not in json.dumps(view(client,scope))
    assert post(client,body).json()==result and len(calls)==1
    body['request_id']='retry-0002';post(client,body);assert len(calls)==2


def test_stale_descriptor_role_unknown_task_or_client_payload_never_calls_model(client,scope,monkeypatch):
    body=request_for(client,scope);calls=install(client,monkeypatch)
    assert post(client,body,'viewer').status_code==403
    assert post(client,body,'reviewer').status_code==403
    for changed in ({'descriptor_hash':'a'*64},{'task_id':'unknown'}):
        assert post(client,{**body,**changed}).status_code==409
    for extra in ({'model_output':output()},{'amount':'1'},{'actor_id':'admin'},{'message':'raw personal data'}):
        assert post(client,{**body,**extra}).status_code==422
    assert not calls


def test_source_change_during_model_call_rejects_suggestion(client,scope,monkeypatch):
    body=request_for(client,scope);store=client.app.state.store
    a=view(client,scope)['artifacts'][0]
    def change():store.revise_object(a['object_id'],a['version'],Scope(**scope),deepcopy(a['data']),status='ACTIVE',created_by='test')
    install(client,monkeypatch,callback=change)
    assert post(client,body).json()['status']=='FAILED'


def test_gateway_uses_dedicated_schema_and_prompt(tmp_path):
    seen={}
    def opener(request,timeout):
        seen.update(json.loads(request.data))
        return FakeResponse({'choices':[{'message':{'content':json.dumps(output())}}]})
    result=DeepSeekProvider(settings_for(tmp_path),opener=opener).complete(stage='MATERIAL_GUIDANCE',request_payload={},input_hash='hash')
    assert result.schema_version==SCHEMA and result.prompt_version==PROMPT
    assert 'prefill' in seen['messages'][0]['content'] and '不得确定实际日期' in seen['messages'][0]['content']
    assert json.loads(seen['messages'][1]['content'])['schema_version']==SCHEMA


def test_real_auth_cross_scope_and_viewer_rejected_before_transport(secured,scope,monkeypatch):
    sign_in(secured)
    body={'scope':scope,'stage':'MATERIAL_GUIDANCE','task_id':'task','descriptor_hash':'a'*64,'request_id':'request-001'}
    calls=install(secured,monkeypatch)
    for key in scope:
        r=secured.post('/api/v1/agent/suggestion',json={**body,'scope':{**scope,key:'unauthorized'}})
        assert r.status_code==403
    assert secured.post('/api/v1/agent/suggestion',json={**body,'model_output':output()}).status_code==403
    sign_in(secured,'reader')
    assert secured.post('/api/v1/agent/suggestion',json=body).status_code==403
    assert not calls


def test_inflight_duplicate_does_not_call_twice_and_unexpected_failure_is_terminal(client,scope,monkeypatch):
    body=request_for(client,scope)
    def duplicate():assert post(client,body).json()['status']=='RUNNING'
    calls=install(client,monkeypatch,fail=RuntimeError('private error body'),callback=duplicate)
    assert post(client,body).json()['status']=='FAILED'
    assert len(calls)==1
    assert 'private error body' not in json.dumps(view(client,scope))


def test_file_hash_failure_before_and_during_call_rejects_old_descriptor(client,scope,monkeypatch):
    body=request_for(client,scope)
    monkeypatch.setattr(client.app.state.service.materials,'source_valid',lambda a:False)
    calls=install(client,monkeypatch)
    assert post(client,body).status_code==409 and not calls
    monkeypatch.setattr(client.app.state.service.materials,'source_valid',lambda a:True)
    def tamper():monkeypatch.setattr(client.app.state.service.materials,'source_valid',lambda a:False)
    calls=install(client,monkeypatch,callback=tamper)
    assert post(client,body).json()['status']=='FAILED' and len(calls)==1


def test_interrupted_final_save_expires_without_recalling_model(client,scope,monkeypatch):
    body=request_for(client,scope);calls=install(client,monkeypatch)
    monkeypatch.setattr('app.material_guidance.clock_seconds',lambda:100)
    store=client.app.state.store;original=store.revise_object
    def broken(*args,**kwargs):raise RuntimeError('simulated unavailable database')
    monkeypatch.setattr(store,'revise_object',broken)
    with pytest.raises(RuntimeError,match='simulated'):
        post(client,body)
    monkeypatch.setattr(store,'revise_object',original)
    assert post(client,body).json()['status']=='RUNNING'
    monkeypatch.setattr('app.material_guidance.clock_seconds',lambda:10000)
    result=post(client,body).json()
    assert result['status']=='FAILED' and result['metadata']['error_code']=='GUIDANCE_EXPIRED'
    assert result['metadata']['mock'] is None
    assert len(calls)==1


def test_late_response_cannot_overwrite_expired_run(client,scope,monkeypatch):
    body=request_for(client,scope)
    monkeypatch.setattr('app.material_guidance.clock_seconds',lambda:100)
    def expire():
        monkeypatch.setattr('app.material_guidance.clock_seconds',lambda:10000)
        assert post(client,body).json()['status']=='FAILED'
    calls=install(client,monkeypatch,callback=expire)
    result=post(client,body).json()
    assert result['status']=='FAILED' and result['metadata']['error_code']=='GUIDANCE_EXPIRED'
    assert len(calls)==1
