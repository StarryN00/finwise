from copy import deepcopy
import pytest
from app.invoice_checks import red_invoice_evidence
from app.invoice_review import ISSUE
from app.ontology.contracts import Scope
from app.ontology.store import digest
from conftest import command
from test_material_review import view
from test_tabular_ingestion import uploaded, parse, xlsx_fixture, INVOICE_HEADERS

NOTE = '被红冲蓝字数电发票号码：26322000000633306346 红字发票信息确认单编号：32058326011138350731 收款人:甲 复核人:乙'


def source(client, scope, *, note=NOTE, net='-100', tax='-13', status='正常', day='2026-03-01', kind='sales_invoices'):
    rows = [INVOICE_HEADERS + ['发票状态', '备注'],
            ['26322000000625714621', day, net, tax, '13%', '甲', status, note]]
    a = uploaded(client, scope, xlsx_fixture([('发票基础信息', rows)]))
    result = parse(client, scope, a, kind).json()['effect']
    return result['artifact'], result['facts'][0]


@pytest.mark.parametrize('kind', ['sales_invoices', 'purchase_invoices'])
def test_original_red_evidence_removes_work_only_without_mutating_financial_data(client, scope, kind):
    a, f = source(client, scope, kind=kind)
    store = client.app.state.store; typed = Scope(**scope)
    before = digest(store.list_objects(None, typed))
    m = view(client, scope)['material_review']; row = m['records'][0]; c = m['counts']
    assert row['automatic_invoice_check']['status'] == 'PASS'
    assert row['automatic_invoice_check']['source_regions'] == ['发票基础信息!H2']
    assert row['automatic_invoice_check']['blue_invoice_no'] == '26322000000633306346'
    assert row['state'] == 'AWAITING_VERIFICATION' and not row['issues']
    assert not m['tasks']  # Do not replace the removed warning with another mandatory verification.
    assert c['system_checked'] == 1 and c['source_verified'] == c['invoice_amount_confirmed'] == c['accounting_usable'] == 0
    assert digest(store.list_objects(None, typed)) == before
    assert ISSUE in store.get_object(f['object_id'], typed)['data']['extraction_issues']
    token = client.app.state.service.invoice_amounts.input_token(typed, f, a)
    response = command(client, scope, 'confirm_invoice_amount', f['object_id'], f['version'], 'stale-ui', {'input_token':token, 'reason':'重复确认'})
    assert response.status_code == 409 and '无需重复' in response.text


@pytest.mark.parametrize('changes', [
    {'note':''}, {'note':'收款人:甲 复核人:乙'},
    {'note':'被红冲蓝字数电发票号码：26322000000633306346'},
    {'note':NOTE.replace('32058326011138350731','3205832601113835073')},
    {'note':NOTE.replace('32058326011138350731','320583260111383507311')},
    {'note':NOTE.replace('26322000000633306346','26322000000625714621')},
    {'note':NOTE+' 被红冲蓝字数电发票号码：26322000000633306347'},
    {'status':'作废'}, {'status':None}, {'net':'0','tax':'0'}, {'net':'-100','tax':'13'},
])
def test_no_blanket_suppression(client, scope, changes):
    _, f = source(client, scope, **changes)
    m = view(client, scope)['material_review']
    assert m['records'][0]['automatic_invoice_check'] is None
    assert any(t['kind']=='INVOICE_AMOUNT' for t in m['tasks'])


def test_cross_period_and_other_issues_remain(client, scope):
    _, f = source(client, scope, day='2026-02-01', tax='-12')
    m = view(client, scope)['material_review']; row=m['records'][0]
    assert row['automatic_invoice_check'] and row['state']=='PERIOD_EXCEPTION'
    assert any('税额' in i for i in row['issues'])
    assert m['counts']['system_checked']==0 and m['counts']['period_exceptions']==1
    assert m['tasks'] and not any(t['kind']=='INVOICE_AMOUNT' for t in m['tasks'])


@pytest.mark.parametrize('change', ['source_version','hash','fact_amount','fake_evidence','archived','formula'])
def test_stale_or_forged_evidence_never_clears_warning(client, scope, change):
    a, f = source(client, scope, note='' if change=='fake_evidence' else NOTE)
    store=client.app.state.store; typed=Scope(**scope)
    if change=='hash':
        (store.database.settings.storage_path/a['data']['storage_path']).write_bytes(b'changed test file')
    elif change in {'source_version','archived'}:
        store.revise_object(a['object_id'],a['version'],typed,a['data'],status='ARCHIVED' if change=='archived' else 'ACTIVE',created_by='test')
    else:
        d=deepcopy(f['data'])
        if change=='fact_amount': d['normalized_value'].update(net_amount='-200.00',tax='-26.00',invoice_total='-226.00')
        elif change=='formula': d['original_value']['formulas']={'H2':'="'+NOTE+'"'}
        else:d['original_value']['values'][-1]=NOTE
        store.revise_object(f['object_id'],f['version'],typed,d,status=f['status'],created_by='test')
    m=view(client,scope)['material_review']
    assert not any(r['automatic_invoice_check'] for r in m['records'])
    assert m['counts']['source_verified']==m['counts']['system_checked']==0


def test_rule_does_not_authenticate_names_or_arithmetic_mismatch(client, scope):
    _, f=source(client,scope)
    d=deepcopy(f['data']);d['normalized_value']['invoice_total']='-114.00'
    assert red_invoice_evidence(d) is None
    d=deepcopy(f['data']);d['normalized_value']['tax']='NaN'
    assert red_invoice_evidence(d) is None
    d=deepcopy(f['data']);d['original_value']['headers'][-1]='任意说明'
    assert red_invoice_evidence(d) is None


def test_exact_columns_are_supported_and_conflicting_references_rejected(client, scope):
    _, f=source(client,scope)
    d=deepcopy(f['data']);o=d['original_value']
    o['headers'][-1:] = ['被红冲蓝字数电发票号码','红字发票信息确认单编号']
    o['values'][-1:] = ['26322000000633306346','32058326011138350731']
    assert red_invoice_evidence(d)
    o['values'][-1] = 32058326011138350731
    assert red_invoice_evidence(d) is None


@pytest.mark.parametrize('header,value', [('是否正数发票','是'),('是否正数发票',''),('发票风险等级','风险'),('发票风险等级',None)])
def test_explicit_risk_or_positive_flag_contradictions_are_not_auto_passed(client, scope, header, value):
    _, f=source(client,scope)
    d=deepcopy(f['data']);d['original_value']['headers'].append(header);d['original_value']['values'].append(value)
    assert red_invoice_evidence(d) is None


@pytest.mark.parametrize('header,value', [('被红冲蓝字数电发票号码',26322000000633306347),
                                        ('红字发票信息确认单编号',32058326011138350732)])
def test_non_text_dedicated_identifier_cannot_be_ignored_when_note_is_complete(client, scope, header, value):
    _, f=source(client,scope)
    d=deepcopy(f['data']);d['original_value']['headers'].append(header);d['original_value']['values'].append(value)
    assert red_invoice_evidence(d) is None


@pytest.mark.parametrize('prior', ['deferred','confirmed'])
def test_existing_human_records_remain_and_automatic_result_does_not_duplicate_them(client, scope, monkeypatch, prior):
    a,f=source(client,scope); service=client.app.state.service;typed=Scope(**scope)
    with monkeypatch.context() as patch:
        patch.setattr(service.invoice_amounts,'automatic_checks',lambda *args: {})
        task=next(t for t in view(client,scope)['material_review']['tasks'] if t['kind']=='INVOICE_AMOUNT')
        if prior=='deferred':
            response=command(client,scope,'defer_material_issue',a['object_id'],a['version'],'old-defer',{'task_id':task['id'],'reason':'历史等待说明'})
        else:
            response=command(client,scope,'confirm_invoice_amount',f['object_id'],f['version'],'old-confirm',{'input_token':task['input_token'],'reason':'历史核对说明'})
        assert response.status_code==200,response.text
    before=digest(service.store.list_objects(None,typed))
    m=view(client,scope)['material_review'];c=m['counts']
    assert not m['tasks'] and c['deferred']==0 and c['source_verified']==c['accounting_usable']==0
    assert c['invoice_amount_confirmed']==(1 if prior=='confirmed' else 0)
    assert digest(service.store.list_objects(None,typed))==before
