from copy import deepcopy
import pytest
from pydantic import ValidationError
from app.ontology.contracts import Scope
from app.materials import VerifyInput
from conftest import command
from test_tabular_ingestion import uploaded,parse,xlsx_fixture,INVOICE_HEADERS


def setup(client,scope):
    a=uploaded(client,scope,xlsx_fixture([('发票',[INVOICE_HEADERS,
        ['I-1','2026-03-01','100','13','13%','甲'],['I-2','2026-03-02','100','13','invalid','甲'],
        ['I-3','2026-02-28','100','13','13%','甲']])]))
    result=parse(client,scope,a).json()['effect']
    return result['artifact'],result['facts']


def view(client,scope):
    return client.post('/api/v1/workbench',json={'scope':scope}).json()


def verify(client,scope,a,f,key='material-verify-1',extra=None,role='accountant'):
    if '_task_id' not in a:
        a['_task_id']=next((t['id'] for t in view(client,scope).get('material_review',{}).get('tasks',[]) if t['kind']=='VERIFY'),'invalid-task')
    return command(client,scope,'verify_source_values',a['object_id'],a['version'],key,
        {'task_id':a['_task_id'],'records':[{'object_id':f['object_id'],'version':f['version']}],**(extra or {})},role=role)


def test_source_review_changes_only_material_layer_and_is_idempotent(client,scope):
    a,facts=setup(client,scope);before=view(client,scope)
    result=verify(client,scope,a,facts[0]);assert result.status_code==200,result.text
    assert verify(client,scope,a,facts[0]).json()['idempotent']
    after=view(client,scope);c=after['material_review']['counts']
    assert c['source_verified']==1 and c['accounting_usable']==0
    assert c['system_checked']==c['awaiting_verification']+c['source_verified']
    assert c['source_verified']<=c['system_checked']
    assert c['system_checked']+c['needs_review']+c['period_exceptions']==c['records']
    assert c['records']==c['source_verified']+c['awaiting_verification']+c['needs_review']+c['period_exceptions']==3
    for field in ['baseline','baseline_validation','progress','vouchers','groups']:
        assert before[field]==after[field]
    check=result.json()['effect']['objects'][0]
    assert check['data']['verified_by']=='alice'
    revoked=command(client,scope,'revoke_source_verification',check['object_id'],check['version'],'material-revoke-1',{})
    assert revoked.status_code==200
    assert view(client,scope)['material_review']['counts']['source_verified']==0


def test_source_review_rejects_gaps_periods_viewers_and_injected_values(client,scope):
    a,f=setup(client,scope)
    for n in [1,2]:assert verify(client,scope,a,f[n],f'material-bad-{n}').status_code==409
    assert verify(client,scope,a,f[0],'material-viewer',role='viewer').status_code==403
    assert verify(client,scope,a,f[0],'material-inject',{'normalized_value':{}}).status_code==409
    assert verify(client,scope,a,f[0],'material-actor',{'owner':'mallory'}).status_code==409


def test_source_verification_invalidates_on_source_hash_or_fact_version_change(client,scope):
    a,f=setup(client,scope);assert verify(client,scope,a,f[0]).status_code==200
    service=client.app.state.service;typed=Scope(**scope)
    service.store.revise_object(f[0]['object_id'],f[0]['version'],typed,{**f[0]['data'],'test_revision':True},status='PARSED',created_by='fixture')
    assert view(client,scope)['material_review']['counts']['source_verified']==0
    current=service.store.get_object(f[0]['object_id'],typed)
    path=service.store.database.settings.storage_path/a['data']['storage_path'];path.write_bytes(b'changed fixture only')
    assert verify(client,scope,a,current,'material-tampered').status_code==409


def test_defer_requires_only_reason_and_does_not_complete_issue(client,scope):
    a,f=setup(client,scope);m=view(client,scope)['material_review']
    task=next(t for t in m['tasks'] if t['kind']=='ISSUE')
    result=command(client,scope,'defer_material_issue',a['object_id'],a['version'],'material-defer-1',{'task_id':task['id'],'reason':'暂无其他材料'})
    assert result.status_code==200,result.text
    saved=result.json()['effect']['object'];assert saved['data']['actor']=='alice'
    n=view(client,scope)['material_review'];assert n['counts']['deferred']==1
    assert n['counts']['source_verified']==0 and n['counts']['needs_review']==m['counts']['needs_review']
    assert next(t for t in n['tasks'] if t['id']==task['id'])['deferred']


def test_closed_period_version_and_scope_checks(client,scope):
    a,f=setup(client,scope);service=client.app.state.service;typed=Scope(**scope)
    other={**scope,'legal_entity_id':'other'};service.create_scope(Scope(**other))
    assert verify(client,other,a,f[0],'material-other').status_code==403
    assert verify(client,scope,{**a,'version':1},f[0],'material-stale').status_code==409
    p=view(client,scope)['period'];service.store.revise_object(p['object_id'],p['version'],typed,p['data'],status='CLOSED',created_by='fixture')
    assert verify(client,scope,a,f[0],'material-closed').status_code==409


def test_reextract_new_version_retains_fact_identity_and_old_review_invalidates(client,scope,monkeypatch):
    a,f=setup(client,scope);assert verify(client,scope,a,f[0]).status_code==200
    monkeypatch.setattr('app.ontology.service.PARSER_VERSION','tabular-test-upgrade')
    response=command(client,scope,'parse_artifact',a['object_id'],a['version'],'material-reextract-upgrade',{'document_kind':'purchase_invoices'})
    assert response.status_code==200,response.text
    result=response.json()['effect'];new=result['facts']
    assert [r['object_id'] for r in new]==[r['object_id'] for r in f]
    assert new[0]['version']>f[0]['version']
    assert view(client,scope)['material_review']['counts']['source_verified']==0


def test_failed_reextract_retires_old_facts_and_cannot_restore_via_reparse(client,scope,monkeypatch):
    from app.tabular import ExtractionError
    from app.ontology.errors import PreconditionFailed
    import pytest
    a,f=setup(client,scope);s=client.app.state.service;typed=Scope(**scope)
    monkeypatch.setattr('app.ontology.service.PARSER_VERSION','failed-parser')
    def fail(*args):raise ExtractionError('unsupported fixture')
    monkeypatch.setattr('app.ontology.service.extract_workbook',fail)
    response=command(client,scope,'parse_artifact',a['object_id'],a['version'],'failed-reparse',{'document_kind':'purchase_invoices'})
    assert response.status_code==200
    assert response.json()['effect']['artifact']['data']['parse_status']=='FAILED'
    assert view(client,scope)['material_review']['counts']['records']==0
    for item in f:
        old=s.store.get_object(item['object_id'],typed);assert old['status']=='SUPERSEDED'
        with pytest.raises(PreconditionFailed):s.reparse_fact(typed,fact_id=old['object_id'],expected_version=old['version'],actor_id='fixture',parser_version='unsafe',normalized_value=old['data']['normalized_value'])


def test_cross_page_verification_is_one_atomic_task_and_unparsed_file_queue(client,scope):
    a=uploaded(client,scope,xlsx_fixture([('发票',[INVOICE_HEADERS]+[[f'I-{i}','2026-03-01','100','13','13%','甲'] for i in range(6)])]))
    m=view(client,scope)['material_review'];assert m['counts']['files']==1 and m['counts']['file_states']['pending']==1
    assert m['tasks'][0]['kind']=='PARSE'
    result=parse(client,scope,a).json()['effect'];a=result['artifact'];f=result['facts']
    tasks=view(client,scope)['material_review']['tasks'];assert len(tasks)==1 and len(tasks[0]['record_ids'])==6
    records=[{'object_id':item['object_id'],'version':item['version']} for item in f]
    response=command(client,scope,'verify_source_values',a['object_id'],a['version'],'cross-page',{'task_id':tasks[0]['id'],'records':records})
    assert response.status_code==200,response.text
    assert response.json()['effect']['verified_count']==6
    assert view(client,scope)['material_review']['counts']['source_verified']==6


def test_verification_task_limit_and_input_boundary(client,scope):
    a=uploaded(client,scope,xlsx_fixture([('发票',[INVOICE_HEADERS]+[[f'I-{i}','2026-03-01','100','13','13%','甲'] for i in range(101)])]))
    result=parse(client,scope,a).json()['effect'];tasks=[t for t in view(client,scope)['material_review']['tasks'] if t['kind']=='VERIFY']
    assert [len(t['record_ids']) for t in tasks]==[100,1]
    refs=[{'object_id':item['object_id'],'version':item['version']} for item in result['facts']]
    VerifyInput.model_validate({'task_id':tasks[0]['id'],'records':refs[:100]})
    with pytest.raises(ValidationError):
        VerifyInput.model_validate({'task_id':tasks[0]['id'],'records':refs})


def test_cross_page_verification_rolls_back_every_record_on_one_stale_version(client,scope):
    a=uploaded(client,scope,xlsx_fixture([('发票',[INVOICE_HEADERS]+[[f'I-{i}','2026-03-01','100','13','13%','甲'] for i in range(6)])]))
    result=parse(client,scope,a).json()['effect'];a=result['artifact'];facts=result['facts']
    task=next(t for t in view(client,scope)['material_review']['tasks'] if t['kind']=='VERIFY')
    records=[{'object_id':item['object_id'],'version':item['version']} for item in facts]
    records[-1]['version']+=1
    response=command(client,scope,'verify_source_values',a['object_id'],a['version'],'cross-page-stale',{'task_id':task['id'],'records':records})
    assert response.status_code==409
    assert view(client,scope)['material_review']['counts']['source_verified']==0


def test_missing_rate_is_not_a_material_error_or_financial_permission(client,scope):
    a=uploaded(client,scope,xlsx_fixture([('发票',[INVOICE_HEADERS,
        ['I-NORATE','2026-03-01','100','13',None,'甲']])]))
    result=parse(client,scope,a).json()['effect'];a=result['artifact'];f=result['facts'][0]
    m=view(client,scope)['material_review']
    assert m['counts']['issue_tasks']==0
    assert m['counts']['system_checked']==1
    assert m['counts']['source_verified']==0
    row=m['records'][0]
    tax=next(x for x in row['comparison'] if x['field']=='tax')
    assert tax['source_value']=='13' and tax['value']=='13.00'
    assert tax['state']=='NORMALIZED_MATCH'
    rate=next(x for x in row['comparison'] if x['field']=='tax_rate')
    assert rate['state']=='MISSING' and rate['value'] is None
    total=next(x for x in row['comparison'] if x['field']=='invoice_total')
    assert total['state']=='DERIVED'
    assert verify(client,scope,a,f).status_code==200
    after=view(client,scope)
    assert after['material_review']['counts']['accounting_usable']==0
    assert not after['baseline_validation']['status']=='VALID'


def test_comparison_never_calls_missing_or_different_sources_equal():
    from app.materials import compare_fields
    data={'original_value':{'sheet':'工资','headers':['姓名','实发工资'],'values':['甲',100]},
          'normalized_value':{'person_name':'乙','actual_salary':'100.00','period':'2026-01'},
          'field_sources':{'person_name':{'region':'工资!A4'},'actual_salary':{'region':'工资!B4'}},
          'source_anchor':{'row':4}}
    rows={r['field']:r for r in compare_fields(data)}
    assert rows['person_name']['state']=='DIFFERENT'
    assert rows['actual_salary']['state']=='NORMALIZED_MATCH'
    assert rows['period']['state']=='UNLOCATED'
    data['field_sources']['actual_salary']['region']='其他表!B4'
    rows={r['field']:r for r in compare_fields(data)}
    assert rows['actual_salary']['state']=='UNLOCATED'
    data['normalized_value']['actual_salary']=None
    data['field_sources']['actual_salary'].update(original_value='not money',status='INVALID')
    rows={r['field']:r for r in compare_fields(data)}
    assert rows['actual_salary']['state']=='DIFFERENT'
    assert rows['actual_salary']['source_value']=='not money'
