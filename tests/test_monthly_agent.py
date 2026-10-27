from copy import deepcopy
from pathlib import Path
import base64
import pytest
from app.monthly_agent import calculate,validate_delivery,MonthlyAgent
from app.ontology.contracts import Scope
from test_tabular_ingestion import xlsx_fixture

def test_calculator_computes_and_preserves_state_without_file_access():
    data={'s':{'sheet':[{'row':1,'values':[1,2]}]}}
    r=calculate("state['total']=sum(tables['s']['sheet'][0]['values']); result=state['total']",data,{}, {},'2026-08')
    assert r['ok'] and r['result']==3 and r['state']['total']==3
    for code in ["result=open('/etc/passwd').read()","import os", "result=(1).__class__", "result=next(x for x in [1]).__class__"]:
        assert not calculate(code,data,{}, {},'2026-08')['ok']

def test_calculator_returns_actionable_error_for_retry():
    r=calculate("result=tables['missing']",{}, {},{},'2026-08')
    assert not r['ok'] and 'KeyError' in r['error']
    assert calculate("result=len(tables)",{}, {},{},'2026-08')['result']==0


def test_standard_calculation_libraries_work_and_errors_keep_line_number():
    code="from decimal import Decimal, ROUND_HALF_UP\nimport json\nresult=json.loads(json.dumps({'amount':str(Decimal('1.235').quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)), 'kind':str(type(state))}))"
    r=calculate(code,{}, {},{},'2026-08')
    assert r['ok'] and r['result']['amount']=='1.24'
    err=calculate("x=1\nresult=state['missing']",{},{},{},'2026-08')
    assert err['error_line']==2
    inspected=calculate("result=[type(state).__name__,hasattr(state,'items'),repr(Decimal('1.20'))]",{},{},{},'2026-08')
    assert inspected['ok'] and inspected['result']==['dict',True,"Decimal('1.20')"]

def test_fabricated_finish_does_not_pass():
    result=validate_delivery({'report':'已全部完成'}, {}, {}, '2026-08',{'original'})
    assert not result['passed'] and result['errors']

def prepare(client,scope):
    client.post('/api/v1/scopes',json=scope)
    s=client.app.state.settings
    for k,v in {'monthly_agent_enabled':True,'agent_send_full_records':True,'agent_mode':'gateway','deepseek_api_key':'fixture'}.items():object.__setattr__(s,k,v)
    content=xlsx_fixture([('Sheet',[['科目编码','日期','借方'],['1002','2026-03-01',100]])])
    obj=client.post('/api/v1/artifacts',json={'scope':scope,'filename':'source.xlsx','content_base64':base64.b64encode(content).decode()}).json()
    return obj['object_id']

def test_start_is_idempotent_read_does_not_execute_and_viewer_cannot_start(client,scope):
    sid=prepare(client,scope)
    r=client.post('/api/v1/monthly/start',json={'scope':scope,'source_ids':[sid]})
    assert r.status_code==200,r.text
    assert client.post('/api/v1/monthly/start',json={'scope':scope,'source_ids':[sid]}).json()['run_id']==r.json()['run_id']
    result=client.get('/api/v1/monthly/runs',params=scope).json()
    assert len(result['runs'])==1 and result['runs'][0]['steps']==[]
    assert client.post('/api/v1/monthly/start',headers={'X-Role':'viewer'},json={'scope':scope,'source_ids':[sid]}).status_code==403
    assert client.app.state.store.list_objects('VoucherVersion',Scope(**scope))==[]

def test_tool_error_retries_in_same_run_and_does_not_touch_business(client,scope):
    sid=prepare(client,scope);client.post('/api/v1/monthly/start',json={'scope':scope,'source_ids':[sid]})
    agent=client.app.state.monthly_agent
    seq=iter([{'tool':'calculate','args':{'code':"result=tables['missing']"},'reason':'读取失败后自动修正'}, {'tool':'inventory','args':{},'reason':'检查实际表格名'}])
    packets=[]
    def model(packet):
        packets.append(packet)
        return next(seq),{'mock':True}
    agent.reader=model
    assert agent.step() and agent.step()
    r=agent.view(Scope(**scope))['runs'][0]
    assert r['status']=='QUEUED' and len(r['steps'])==2 and r['steps'][0]['error']
    assert client.app.state.store.list_objects('MonthlyAgentDelivery',Scope(**scope))==[]
    assert packets[1]['history'][0]['args']['code']=="result=tables['missing']"


def test_bank_date_observation_cannot_be_overwritten_to_make_period_match():
    d,tables=validation_fixture()
    d['source_roles']['pdf']='bank'
    reading={'ocr':{'statement':{'rows':[dict(sequence=1,transaction_date='2026-09-01',credit=100,debit=0,balance=100)],'totals':dict(credit_total=100,debit_total=0,closing_balance=100)}},'views':[{'page':1}]}
    d['bank']=[dict(sequence=1,date='2026-09-01',income=100,expense=0,balance=100,source=dict(source_id='pdf',page=1,row=1))]
    d['findings']=[dict(title='日期矛盾',detail='保留原始读取值，尚未确定',evidence=[dict(source_id='pdf',page=1,row=1)],affected_vouchers=['记-001'])]
    assert validate_delivery(d,tables,{'pdf':reading},'2026-08',set(d['source_roles']))['passed']
    d['bank'][0]['sequence']='1'
    assert validate_delivery(d,tables,{'pdf':reading},'2026-08',set(d['source_roles']))['passed']
    d['bank'][0]['date']='2026-08-01'
    assert not validate_delivery(d,tables,{'pdf':reading},'2026-08',set(d['source_roles']))['passed']
    d['bank'][0]['sequence']='999'
    assert not validate_delivery(d,tables,{'pdf':reading},'2026-08',set(d['source_roles']))['passed']

def test_code_stays_outside_formal_financial_writes():
    source=Path('app/monthly_agent.py').read_text()
    assert 'create_initial_object(DELIVERY' in source
    assert 'create_initial_object(ObjectType.VOUCHER_VERSION' not in source
    assert 'monthly_sandbox.py' in source


def validation_fixture():
    def sheet(values):return {'Sheet':[{'row':i+1,'values':v} for i,v in enumerate(values)]}
    def ref(s,row):return {'source_id':s,'sheet':'Sheet','row':row}
    tables={
        'journal':sheet([['1002','2026-08-01','记-001',100,0],['4001','2026-08-01','记-001',0,100]]),
        'opening':sheet([['1002','银行',0,0],['4001','资本',0,0]]),
        'balance':sheet([['1002','银行',100,0],['4001','资本',0,100]]),
        'invoice':sheet([['发票号码','金额','税额'],['12345678',100,0]])}
    d={'period':'2026-08','source_roles':{k:k for k in tables},'report':'候选结果与来源对照；不表示正式过账。'*20,
       'bindings':{'journal':dict(source_id='journal',sheet='Sheet',code=0,date=1,voucher=2,debit=3,credit=4),
                   'opening':dict(source_id='opening',sheet='Sheet',code=0,name=1,debit=2,credit=3),
                   'reported_balance':dict(source_id='balance',sheet='Sheet',code=0,name=1,debit=2,credit=3)},
       'opening':[dict(code=c,debit=0,credit=0,source=ref('opening',i)) for i,c in enumerate(['1002','4001'],1)],
       'entries':[dict(code=c,date='2026-08-01',voucher='记-001',debit=de,credit=cr,source=ref('journal',i)) for i,(c,de,cr) in enumerate([('1002',100,0),('4001',0,100)],1)],
       'invoices':[dict(kind='进项',number='12345678',net=100,tax=0,gross=100,source=ref('invoice',2))],
       'bank':[],'findings':[]}
    return d,tables


def test_independent_validation_accepts_source_backed_result():
    d,tables=validation_fixture()
    result=validate_delivery(d,tables,{},'2026-08',set(tables))
    assert result['passed'],result['errors']
    assert len(result['trial_balance'])==2


@pytest.mark.parametrize('corruption',['balanced_fabrication','missing_entry','duplicate_invoice','invented_source'])
def test_independent_validation_rejects_plausible_but_unbacked_delivery(corruption):
    d,tables=validation_fixture()
    if corruption=='balanced_fabrication':
        d['entries'][0]['debit']=101;d['entries'][1]['credit']=101
    elif corruption=='missing_entry':d['entries'].pop()
    elif corruption=='duplicate_invoice':d['invoices'].append(deepcopy(d['invoices'][0]))
    else:d['invoices'][0]['source']['row']=999
    assert not validate_delivery(d,tables,{},'2026-08',set(tables))['passed']


def test_frozen_runtime_change_blocks_instead_of_resuming(client,scope):
    sid=prepare(client,scope)
    run_id=client.post('/api/v1/monthly/start',json={'scope':scope,'source_ids':[sid]}).json()['run_id']
    agent=client.app.state.monthly_agent;sc=Scope(**scope);run=agent.store.get_object(run_id,sc)
    agent.store.revise_object(run_id,run['version'],sc,{**run['data'],'code_hash':'previous-version'},status='QUEUED',created_by='test')
    agent.reader=lambda packet:pytest.fail('must stop before calling the model')
    assert agent.step()
    assert agent.view(sc)['runs'][0]['status']=='BLOCKED'


def test_monthly_routes_enforce_authenticated_scope_and_server_role(tmp_path,scope):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.config import Settings
    from app.auth import create_user,grant_scope
    app=create_app(Settings(root=Path(__file__).resolve().parents[1],database_path=tmp_path/'auth.db',storage_path=tmp_path/'files',require_auth=True))
    create_user(app.state.database,'monthly-reader','test-only-password','viewer')
    grant_scope(app.state.database,'monthly-reader',Scope(**scope))
    app.state.service.create_scope(Scope(**scope))
    client=TestClient(app)
    assert client.get('/api/v1/monthly/runs',params=scope).status_code==401
    signed=client.post('/api/v1/auth/login',json={'username':'monthly-reader','password':'test-only-password'})
    client.headers['X-CSRF-Token']=signed.json()['csrf_token']
    assert client.get('/api/v1/monthly/runs',params=scope).status_code==200
    assert client.get('/api/v1/monthly/runs',params={**scope,'legal_entity_id':'other'}).status_code==403
    assert client.post('/api/v1/monthly/start',headers={'X-Role':'admin'},json={'scope':scope,'source_ids':['original']}).status_code==403


def test_expired_worker_lease_recovers_persisted_state_in_same_task(client,scope):
    sid=prepare(client,scope)
    run_id=client.post('/api/v1/monthly/start',json={'scope':scope,'source_ids':[sid]}).json()['run_id']
    store=client.app.state.store;sc=Scope(**scope);run=store.get_object(run_id,sc)
    store.revise_object(run_id,run['version'],sc,{**run['data'],'lease_until':0,'state':{'progress':'kept'}},status='RUNNING',created_by='test')
    restarted=MonthlyAgent(client.app.state.service)
    restarted.reader=lambda packet:({'tool':'calculate','args':{'code':"result=state['progress']"},'reason':'恢复既有状态'}, {'mock':True})
    assert restarted.step()
    result=store.get_object(run_id,sc)
    assert result['data']['steps'][0]['result']['result']=='kept'
    assert len(store.list_objects('MonthlyAgentRun',sc))==1
