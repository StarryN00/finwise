from copy import deepcopy
import json
import pytest

from app.ontology.contracts import Scope
from app.ontology.gateway import GatewayResult
from app.ontology.store import digest
from app.problem_review import STAGE, ReviewOutput, ProblemReview
from conftest import command
from test_invoice_amount_review import setup_invoices
from test_material_review import view


def queued(client, scope):
    setup_invoices(client,scope)
    wb=view(client,scope)
    p=wb['period']
    result=command(client,scope,'request_problem_review',p['object_id'],p['version'],'review-1')
    assert result.status_code==200,result.text
    return result.json(), wb


def install(client,monkeypatch,output=None,callback=None):
    calls=[]
    def complete(scope,*,stage,sanitized_input):
        calls.append(sanitized_input)
        if callback:callback()
        value=output or {'outcome':'SUPPORTED','evidence_refs':[sanitized_input['evidence'][0]['id']],
                        'check_ids':['SOURCE_FIELDS'],'explanation':'可以通过并制证。','uncertainties':[]}
        return GatewayResult(value,'fixture','fixture',True,'test',digest(sanitized_input),digest(value),1,{'total_tokens':5})
    monkeypatch.setattr(client.app.state.service.gateway,'complete',complete)
    return calls


def test_queue_idempotency_readonly_and_no_business_writes(client,scope,monkeypatch):
    result,before=queued(client,scope);svc=client.app.state.service
    calls=install(client,monkeypatch)
    p=before['period']
    again=command(client,scope,'request_problem_review',p['object_id'],p['version'],'review-1')
    assert again.json()['idempotent']
    view(client,scope);view(client,scope)
    assert not calls
    assert svc.problem_review.run_once()
    after=view(client,scope)
    for key in ('artifacts','baseline','data_readiness','groups','vouchers','invoice_amount_review'):
        assert before[key]==after[key]
    assert after['material_review']['counts']==before['material_review']['counts']
    job=next(j for j in after['problem_review']['jobs'] if j['status'] not in {'QUEUED'})
    assert job['status']!='PASSED'
    assert '制证' not in job['data']['result']['message']
    encoded=json.dumps(calls,ensure_ascii=False)
    for secret in ('RED-1','甲','113','legal-a','.xlsx'):assert secret not in encoded


@pytest.mark.parametrize('output',[
    {'outcome':'SUPPORTED','evidence_refs':['invented'],'check_ids':[],'explanation':'通过','uncertainties':[]},
    {'outcome':'SUPPORTED','evidence_refs':['record-1'],'check_ids':['run_sql'],'explanation':'通过','uncertainties':[]},
    {'outcome':'SUPPORTED','evidence_refs':['record-1'],'check_ids':[],'explanation':'通过','uncertainties':[],'execute':'delete'},
])
def test_bad_model_output_preserves_issues(client,scope,monkeypatch,output):
    _,before=queued(client,scope);install(client,monkeypatch,output)
    client.app.state.service.problem_review.run_once()
    after=view(client,scope)
    assert any(j['status']=='FAILED' for j in after['problem_review']['jobs'])
    assert before['material_review']['counts']==after['material_review']['counts']


def test_permissions_payload_and_scope(client,scope):
    _,before=queued(client,scope);p=before['period']
    assert command(client,scope,'request_problem_review',p['object_id'],p['version'],'deny-review',role='reviewer').status_code==403
    assert command(client,scope,'request_problem_review',p['object_id'],p['version'],'bad-review',{'amount':'0'}).status_code==409
    other={**scope,'legal_entity_id':'other'}
    assert command(client,other,'request_problem_review',p['object_id'],p['version'],'foreign-review').status_code==403
    assert command(client,scope,'request_problem_review',p['object_id'],99,'version-review').status_code==409


def test_changed_input_discards_late_result(client,scope,monkeypatch):
    _,before=queued(client,scope);svc=client.app.state.service;s=Scope(**scope)
    artifact=before['artifacts'][0]
    def change():
        svc.store.revise_object(artifact['object_id'],artifact['version'],s,artifact['data'],status='ACTIVE',created_by='test')
    install(client,monkeypatch,callback=change)
    svc.problem_review.run_once()
    jobs=view(client,scope)['problem_review']['jobs']
    assert any(j['status']=='STALE' for j in jobs)
    assert not any(j['status']=='PASSED' for j in jobs)


def test_model_cannot_dismiss_without_matching_local_proof():
    output=ReviewOutput(outcome='SUPPORTED',evidence_refs=['r'],check_ids=[],explanation='已解决',uncertainties=[])
    result=ProblemReview.verdict(output,{'evidence':[{'id':'r'}]},[],[],{'reason':'其他','record_ids':['f']})
    assert result['status']=='INSUFFICIENT' and not result['dismissed']


def test_failed_retry_and_changed_version(client,scope,monkeypatch):
    _,before=queued(client,scope);svc=client.app.state.service
    install(client,monkeypatch,{'bad':1});svc.problem_review.run_once()
    job=next(j for j in view(client,scope)['problem_review']['jobs'] if j['status']=='FAILED')
    r=command(client,scope,'retry_problem_review',job['object_id'],job['version'],'retry-review')
    assert r.status_code==200,r.text
    assert r.json()['effect']['object']['status']=='QUEUED'
    assert command(client,scope,'retry_problem_review',job['object_id'],job['version'],'old-retry').status_code==409


def test_proven_red_offset_projection_and_invalidation(client,scope,monkeypatch):
    from test_problem_evidence import inputs
    from test_tabular_ingestion import xlsx_fixture
    from app.tabular import column_name
    from app.invoice_checks import BLUE_LABEL, CONFIRM_LABEL
    import hashlib
    svc=client.app.state.service;s=Scope(**scope)
    svc.create_scope(s)
    artifacts,facts,_=inputs(scope)
    a=artifacts[0];a['data'].update(filename='fixture.xlsx',source_purpose='business',parse_options={'document_kind':'sales_invoices'})
    headers=list(facts[0]['data']['normalized_value'])+[BLUE_LABEL,CONFIRM_LABEL]
    rows=[headers]
    for f in facts:
        d=f['data'];values=list(d['normalized_value'].values())+d['original_value']['values']
        rows.append(values);d['original_value'].update(headers=headers,values=values)
        for i,key in enumerate(d['normalized_value']):d['field_sources'][key]['region']=f"发票!{column_name(i+1)}{d['original_value']['row']}"
    content=xlsx_fixture([('发票',rows)])
    (svc.store.database.settings.storage_path/'fixture.xlsx').write_bytes(content)
    a['data'].update(storage_path='fixture.xlsx',sha256=hashlib.sha256(content).hexdigest())
    svc.store.create_initial_object('SourceArtifact',s,a['data'],status='ACTIVE',object_id='a')
    svc.store.revise_object('a',1,s,a['data'],status='ACTIVE',created_by='fixture')
    for f in facts:svc.store.create_initial_object('FactRecord',s,f['data'],status=f['status'],object_id=f['object_id'])
    before=view(client,scope);install(client,monkeypatch)
    with svc.store.database.transaction():svc.problem_review.enqueue(s,'test')
    assert svc.problem_review.run_once()
    after=view(client,scope)
    assert any(j['status']=='PASSED' for j in after['problem_review']['jobs'])
    row=next(r for r in after['material_review']['records'] if r['object_id']=='f0')
    assert row['state']=='AWAITING_VERIFICATION' and not row['issues']
    assert not row['eligible']  # no relaxation of original verification gates
    assert after['material_review']['counts']['source_verified']==0
    assert before['material_review']['counts']['accounting_usable']==after['material_review']['counts']['accounting_usable']
    for key in ('artifacts','baseline','data_readiness','groups','vouchers'):assert before[key]==after[key]
    red=svc.store.get_object('f1',s)
    svc.store.revise_object('f1',red['version'],s,red['data'],status='SUPERSEDED',created_by='test')
    stale=view(client,scope)
    assert not any(j['valid'] for j in stale['problem_review']['jobs'])
    assert next(r for r in stale['material_review']['records'] if r['object_id']=='f0')['issues']


def test_expired_run_recovery_does_not_call_model_again(client,scope,monkeypatch):
    queued(client,scope);svc=client.app.state.service;s=Scope(**scope)
    job=svc.store.list_objects('ProblemReview',s)[0]
    run=svc.store.create_initial_object('ModelRun',s,{'stage':STAGE},status='RUNNING')
    svc.store.revise_object(job['object_id'],job['version'],s,{**job['data'],'expires_at':0,'model_run_id':run['object_id']},status='RUNNING',created_by='test')
    calls=install(client,monkeypatch)
    svc.problem_review.run_once()
    assert svc.store.get_object(job['object_id'],s)['status']=='FAILED'
    assert svc.store.get_object(run['object_id'],s)['status']=='FAILED'
    assert len(calls)<=1  # remaining independently queued job, never the expired one
