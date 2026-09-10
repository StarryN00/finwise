from copy import deepcopy
from dataclasses import replace
import json
import pytest
from app.payroll_mapping import bounded_sheets, structure_packet, extract_mapped, validated_proposal, layout_signature
from app.ontology.contracts import Scope
from app.ontology.gateway import GatewayResult, GatewayFailure
from app.tabular import ExtractionError
from conftest import command
from test_tabular_ingestion import uploaded,xlsx_fixture


def content(period='2026-03',headers=None):
    return xlsx_fixture([('秘密工资表',[['工资表 所属期 '+period],headers or ['员工','底薪','实付','公司社保','个人社保','住房公积金'],['员工秘密甲','2000','3500.18','400','200','80'],['员工秘密乙','2100','bad','450','210','90'],['合计','4100','3500.18']])])


def proposal():
    return {'sheets':[{'sheet_index':0,'header_rows':[2],'fields':{'person_name':'A','basic_salary':'B','actual_salary':'C','employer_social':'D','employee_social':'E'},'period_cell':'A1'}],'confidence':.94}


def test_mapping_redacts_identity_amount_filename_and_formula():
    packet=structure_packet(bounded_sheets(content()))
    data=json.dumps(packet,ensure_ascii=False)
    for private in ['秘密','3500.18','2000','员工秘密甲','2026-03']:assert private not in data
    assert '实付' in data and '公司' in data and '<NUMBER>' not in data # fixture uses strings


def test_local_mapping_preserves_invalid_employee_and_unmapped_contribution():
    result=extract_mapped(bounded_sheets(content()),proposal(),'2026-03')
    assert len(result['records'])==2
    a,b=result['records'];assert a['normalized_value']['actual_salary']=='3500.18'
    assert b['normalized_value']['actual_salary'] is None
    assert b['original_value']['values'][2]=='bad'
    assert any('unmapped_F' in i for i in a['extraction_issues'])
    assert a['field_sources']['actual_salary']['region']=='秘密工资表!C3'
    assert a['period_check']=='PASS'
    assert result['checks']['excluded_rows'][-1]['reason'].startswith('汇总')


@pytest.mark.parametrize('mutate',[
    lambda p:p['sheets'][0]['fields'].update(actual_salary='ZZ'),
    lambda p:p['sheets'][0]['fields'].update(tax='C'),
    lambda p:p['sheets'][0]['fields'].update(arbitrary_amount='B'),
    lambda p:p['sheets'][0].update(header_rows=[200]),
    lambda p:p['sheets'][0].update(period_cell='A9000'),
    lambda p:p.update(code='print(1)'),
    lambda p:p['sheets'].append(deepcopy(p['sheets'][0])),
])
def test_candidate_rejects_invalid_schema_or_sources(mutate):
    p=proposal();mutate(p)
    with pytest.raises(ExtractionError):validated_proposal(p,bounded_sheets(content()))


def test_missing_period_is_not_filled_from_scope():
    p=proposal();p['sheets'][0]['period_cell']=None
    records=extract_mapped(bounded_sheets(content()),p,'2026-03')['records']
    assert all(r['period_check']=='PERIOD_EXCEPTION' and r['normalized_value']['period'] is None for r in records)


def test_reordered_columns_require_new_structure_but_same_format_new_period_matches():
    p=proposal();s=bounded_sheets(content())
    assert layout_signature(s,p)==layout_signature(bounded_sheets(content('2026-04')),p)
    assert layout_signature(s,p)!=layout_signature(bounded_sheets(content(headers=['实付','底薪','员工','公司社保','个人社保','住房公积金'])),p)


def setup(client,app,scope,raw=None):
    a=uploaded(client,scope,raw or content())
    calls=[]
    def complete(s,**kwargs):
        calls.append(kwargs)
        return GatewayResult(proposal(),'deepseek','test-model',False,'mapping-test','input','output',10,{'total_tokens':20})
    app.state.service.gateway.complete=complete
    return a,calls


def request(client,scope,a,key='map-request'):
    return command(client,scope,'request_payroll_mapping',a['object_id'],a['version'],key)


def test_queue_candidate_confirm_uses_existing_fact_gates_and_idempotency(client,app,scope):
    a,calls=setup(client,app,scope)
    response=request(client,scope,a);assert response.status_code==200,response.text
    assert request(client,scope,a).json()['idempotent']
    assert app.state.service.payroll_mapping.run_once()
    assert len(calls)==1
    overview=app.state.service.workbench(Scope(**scope));j=overview['payroll_mappings'][-1]
    assert j['status']=='REVIEW' and not app.state.store.list_objects('FactRecord',Scope(**scope))
    payload={'proposal':j['data']['proposal'],'mapping_confirmed':True}
    r=command(client,scope,'apply_payroll_mapping',j['object_id'],j['version'],'map-apply',payload)
    assert r.status_code==200,r.text
    assert command(client,scope,'apply_payroll_mapping',j['object_id'],j['version'],'map-apply',payload).json()['idempotent']
    after=app.state.service.workbench(Scope(**scope))
    assert after['material_review']['counts']['source_verified']==0
    assert after['material_review']['counts']['accounting_usable']==0
    assert after['baseline']['status']=='DRAFT'
    assert r.json()['effect']['object']['data']['confirmed_by']=='alice'


def test_failure_persists_and_retry_is_explicit(client,app,scope):
    a,calls=setup(client,app,scope)
    def fail(*args,**kwargs):raise GatewayFailure('超时','PROVIDER_UNAVAILABLE')
    app.state.service.gateway.complete=fail
    assert request(client,scope,a).status_code==200
    app.state.service.payroll_mapping.run_once()
    jobs=app.state.service.workbench(Scope(**scope))['payroll_mappings'];assert jobs[-1]['status']=='FAILED'
    assert not app.state.service.payroll_mapping.run_once()
    r=request(client,scope,a,'map-retry');assert r.json()['effect']['object']['status']=='QUEUED'


def test_permissions_and_old_version_rejected(client,app,scope):
    a,calls=setup(client,app,scope)
    assert command(client,scope,'request_payroll_mapping',a['object_id'],a['version'],'map-viewer',role='viewer').status_code==403
    assert request(client,scope,a).status_code==200;app.state.service.payroll_mapping.run_once()
    j=app.state.service.workbench(Scope(**scope))['payroll_mappings'][-1]
    store=app.state.store;store.revise_object(a['object_id'],a['version'],Scope(**scope),a['data'],status='ARCHIVED',created_by='test')
    r=command(client,scope,'apply_payroll_mapping',j['object_id'],j['version'],'map-invalid',{'proposal':proposal(),'mapping_confirmed':True})
    assert r.status_code==409


def test_low_confidence_remains_review_and_never_auto_applies(client,app,scope):
    a,calls=setup(client,app,scope)
    p=proposal();p['confidence']=.1
    app.state.service.gateway.complete=lambda *args,**kw:GatewayResult(p,'deepseek','m',False,'p','i','o',1,{})
    request(client,scope,a);app.state.service.payroll_mapping.run_once()
    j=app.state.service.workbench(Scope(**scope))['payroll_mappings'][-1]
    assert j['status']=='REVIEW' and j['data']['proposal']['confidence']==.1
    assert app.state.store.get_object(a['object_id'],Scope(**scope))['version']==1


def slips(extra=None):
    rows=[['工资表 所属期 2026-03'],['姓名','实发工资','单位缴','个人缴'],['甲',100,20,10],
          ['险种','单位缴费','个人缴费'],['养老',20,10],['工资表 所属期 2026-03'],
          ['姓名','实发工资','单位缴','个人缴'],['乙',200,30,15]]
    if extra is not None:rows.append(extra)
    p={'sheets':[{'sheet_index':0,'header_rows':[2],'fields':{'person_name':'A','actual_salary':'B'},'period_cell':'A1','row_mode':'slips'}],'confidence':.9}
    return bounded_sheets(xlsx_fixture([('工资条',rows)])),p


def test_slips_only_exclude_explicit_insurance_subtable():
    s,p=slips();out=extract_mapped(s,p,'2026-03')
    assert [r['normalized_value']['actual_salary'] for r in out['records']]==['100.00','200.00']
    assert any('社保子表' in r['reason'] for r in out['checks']['excluded_rows'])


@pytest.mark.parametrize('extra',[[None,300],[None,300,'丙'],['丙',300],['不明文本'],[None,None,'不明文本']])
def test_slips_unknown_rows_fail_instead_of_disappearing(extra):
    s,p=slips(extra)
    with pytest.raises(ExtractionError,match='遗漏员工'):extract_mapped(s,p,'2026-03')


def test_later_header_cannot_hide_prior_employee():
    s,p=slips();p['sheets'][0]['header_rows']=[7]
    with pytest.raises(ExtractionError,match='更早'):extract_mapped(s,p,'2026-03')


def test_slips_changed_period_is_not_overwritten_by_first_title():
    s,p=slips();s[0]['rows'][5]['values'][0]='工资表 所属期 2026-04'
    assert extract_mapped(s,p,'2026-03')['records'][1]['period_check']=='PERIOD_EXCEPTION'


@pytest.mark.parametrize('location',['title','column','detail'])
def test_non_yuan_units_rejected_everywhere(location):
    s=bounded_sheets(content());r={'title':0,'column':1,'detail':2}[location]
    s[0]['rows'][r]['values'].append('单位：万元')
    with pytest.raises(ExtractionError,match='金额单位'):extract_mapped(s,proposal(),'2026-03')


def test_changed_mapping_requires_fresh_preview_and_saves_actual_rows(client,app,scope):
    a,_=setup(client,app,scope);request(client,scope,a);app.state.service.payroll_mapping.run_once()
    j=app.state.service.workbench(Scope(**scope))['payroll_mappings'][-1];p=deepcopy(j['data']['proposal']);p['sheets'][0]['fields'].update(employee_housing_fund='F')
    assert command(client,scope,'apply_payroll_mapping',j['object_id'],j['version'],'no-preview',{'proposal':p,'mapping_confirmed':True}).status_code==409
    r=command(client,scope,'preview_payroll_mapping',j['object_id'],j['version'],'preview-map',{'proposal':p});assert r.status_code==200,r.text
    j=r.json()['effect']['object'];assert not app.state.store.list_objects('FactRecord',Scope(**scope))
    r=command(client,scope,'apply_payroll_mapping',j['object_id'],j['version'],'apply-preview',{'proposal':j['data']['proposal'],'mapping_confirmed':True});assert r.status_code==200,r.text
    assert r.json()['effect']['object']['data']['preview']['records'][0]['normalized_value']['employee_housing_fund']=='80.00'
    a=r.json()['effect']['artifact'];j2=request(client,scope,a,'reopen-applied').json()['effect']['object']
    assert j2['status']=='APPLIED' and j2['object_id']==j['object_id']
    assert app.state.store.get_object(a['object_id'],Scope(**scope))['version']==a['version']


def test_late_result_after_source_change_is_not_usable(client,app,scope):
    a,_=setup(client,app,scope)
    def complete(*args,**kwargs):
        app.state.store.revise_object(a['object_id'],a['version'],Scope(**scope),a['data'],status='ARCHIVED',created_by='test')
        return GatewayResult(proposal(),'fixture','m',False,'p','i','o',1,{})
    app.state.service.gateway.complete=complete;request(client,scope,a);app.state.service.payroll_mapping.run_once()
    j=app.state.store.list_objects('PayrollMapping',Scope(**scope))[-1]
    assert j['status']=='FAILED' and not app.state.store.list_objects('FactRecord',Scope(**scope))


def test_continuous_table_to_slips_is_not_same_layout():
    s,p=slips();short=deepcopy(s);short[0]['rows']=short[0]['rows'][:3]
    assert layout_signature(short,p)!=layout_signature(s,p)


def test_confirmed_format_reuses_only_same_company_and_rereads_period(client,app,scope):
    a,calls=setup(client,app,scope);request(client,scope,a);app.state.service.payroll_mapping.run_once()
    j=app.state.service.workbench(Scope(**scope))['payroll_mappings'][-1]
    r=command(client,scope,'apply_payroll_mapping',j['object_id'],j['version'],'template-apply',{'proposal':j['data']['proposal'],'mapping_confirmed':True});assert r.status_code==200
    following={**scope,'accounting_period_id':'2026-04','baseline_id':'baseline-a-2026-04'}
    a2=uploaded(client,following,content('2026-04'))
    j2=request(client,following,a2,'template-month').json()['effect']['object']
    assert j2['status']=='REVIEW' and j2['data']['origin']=='CONFIRMED_FORMAT'
    assert j2['data']['preview']['records'][0]['normalized_value']['period']=='2026-04'
    assert len(calls)==1
    other={**scope,'legal_entity_id':'other-company','baseline_id':'baseline-other'}
    a3=uploaded(client,other,content());j3=request(client,other,a3,'template-other').json()['effect']['object']
    assert j3['status']=='QUEUED' and 'reused_from' not in j3['data']
    assert command(client,other,'apply_payroll_mapping',j['object_id'],j['version'],'cross-scope-apply',{'proposal':j['data']['proposal'],'mapping_confirmed':True}).status_code in (403,404,409)


def test_client_cannot_override_row_mode_during_preview(client,app,scope):
    a,_=setup(client,app,scope);request(client,scope,a);app.state.service.payroll_mapping.run_once()
    j=app.state.service.workbench(Scope(**scope))['payroll_mappings'][-1];p=deepcopy(j['data']['proposal']);p['sheets'][0]['row_mode']='slips'
    assert command(client,scope,'preview_payroll_mapping',j['object_id'],j['version'],'mode-change',{'proposal':p}).status_code==409


def test_formula_and_missing_employee_are_not_silently_verified():
    s=bounded_sheets(content());s[0]['rows'][2]['formulas']={'C3':'=SUM(B3,1500.18)'};s[0]['rows'][3]['values'][0]=None
    records=extract_mapped(s,proposal(),'2026-03')['records']
    assert len(records)==2
    assert any('公式' in i for i in records[0]['extraction_issues'])
    assert any('person_name' in i for i in records[1]['extraction_issues'])


@pytest.mark.parametrize('header_rows',[[2,3],[2,4]])
def test_header_cannot_swallow_employee_row(header_rows):
    s=bounded_sheets(content());p=proposal();p['sheets'][0]['header_rows']=header_rows
    with pytest.raises(ExtractionError):extract_mapped(s,p,'2026-03')


def test_vertical_merged_headers_do_not_overlap_employee_row():
    from app.payroll_mapping import primary_blocks
    rows=[['工资表 所属期 2026-03'],['姓名','实发工资','社保'],[None,None,'个人'],['甲',100,20],
          ['工资表 所属期 2026-03'],['姓名','实发工资','社保'],[None,None,'个人'],['乙',200,40]]
    s=bounded_sheets(xlsx_fixture([('工资条',rows)]));s[0]['merged_cells']=[(1,2,1,3),(2,2,2,3),(1,6,1,7),(2,6,2,7)]
    p={'sheets':[{'sheet_index':0,'header_rows':[2,3],'fields':{'person_name':'A','actual_salary':'B'},'period_cell':'A1','row_mode':'slips'}],'confidence':.9}
    assert primary_blocks(s[0],p['sheets'][0])==[[2,3],[6,7]]
    out=extract_mapped(s,p,'2026-03');assert len(out['records'])==2
    assert [r['original_value']['row'] for r in out['records']]==[4,8]


@pytest.mark.parametrize('change',['period','column'])
def test_table_does_not_apply_stale_semantics_to_later_segment(change):
    rows=[['工资表 所属期 2026-03'],['姓名','实发工资','个人社保'],['甲',100,20],
          ['工资表 所属期 '+('2026-04' if change=='period' else '2026-03')],
          ['姓名','实发工资','单位社保' if change=='column' else '个人社保'],['乙',200,40]]
    s=bounded_sheets(xlsx_fixture([('工资',rows)]));p={'sheets':[{'sheet_index':0,'header_rows':[2],'fields':{'person_name':'A','actual_salary':'B','employee_social':'C'},'period_cell':'A1'}],'confidence':.9}
    with pytest.raises(ExtractionError):extract_mapped(s,p,'2026-03')


@pytest.mark.parametrize('unit',['百元','美元','EUR','未知单位'])
def test_explicit_unsupported_currency_unit_refused(unit):
    s=bounded_sheets(content());s[0]['rows'][0]['values'].append('金额单位：'+unit)
    with pytest.raises(ExtractionError,match='单位'):extract_mapped(s,proposal(),'2026-03')


def test_uncached_formula_row_and_duplicates_remain_visible():
    s=bounded_sheets(content());s[0]['rows'][3]['values']=[None]*6;s[0]['rows'][3]['formulas']={'A4':'=A3','C4':'=C3'}
    r=extract_mapped(s,proposal(),'2026-03')['records'];assert len(r)==2 and r[1]['extraction_issues']
    s=bounded_sheets(content());s[0]['rows'][3]['values']=deepcopy(s[0]['rows'][2]['values'])
    r=extract_mapped(s,proposal(),'2026-03')['records'];assert len(r)==2 and all(any('重复' in i for i in x['extraction_issues']) for x in r)


def test_identity_keyword_cannot_hide_extra_employee():
    s,p=slips(['丙',300,'账号:123'])
    with pytest.raises(ExtractionError,match='遗漏员工'):extract_mapped(s,p,'2026-03')


def test_full_insurance_name_allowed_only_in_bounded_subtable():
    s,p=slips();s[0]['rows'][4]['values'][0]='养老保险'
    assert len(extract_mapped(s,p,'2026-03')['records'])==2


def test_later_net_and_gross_column_swap_is_rejected():
    rows=[['工资表 所属期 2026-03'],['姓名','实发工资','应发工资'],['甲',90,100],['姓名','应发工资','实发工资'],['乙',200,180]]
    s=bounded_sheets(xlsx_fixture([('工资',rows)]));p={'sheets':[{'sheet_index':0,'header_rows':[2],'fields':{'person_name':'A','actual_salary':'B'},'period_cell':'A1'}],'confidence':.9}
    with pytest.raises(ExtractionError,match='锚点列'):extract_mapped(s,p,'2026-03')


@pytest.mark.parametrize('standalone',[True,False])
def test_reporting_company_is_not_currency_unit(standalone):
    s=bounded_sheets(content());s[0]['rows'][0]['values']+=['单位','示例有限公司'] if standalone else ['单位：示例有限公司']
    assert len(extract_mapped(s,proposal(),'2026-03')['records'])==2
