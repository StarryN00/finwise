from copy import deepcopy

from app.issue_triage import classify_task


def task(kind='ISSUE', reason='发票状态：发票状态须人工核对', field='invoice_status'):
    return {'id':'t','kind':kind,'reason':reason,'title':reason,'record_ids':['f'],
            'descriptor':{'options':[{'id':'supplement','available':True}],
                          'presentation':{'type_label':'发票状态待核对','explanation':'旧解释',
                                          'records':[{'id':'f','focus_fields':[field]}]}}}


def row(field='invoice_status', raw='已红冲-全额', value='已红冲-全额', state='DIRECT_MATCH'):
    return {'object_id':'f','source_anchor':{'region':'发票!A2:S2'},
            'comparison':[{'field':field,'source_value':raw,'value':value,'state':state,'region':'发票!O2'}]}


def test_normal_status_is_a_check_signal_not_a_business_question():
    t=task(); before=deepcopy(t)
    result=classify_task(t,[row()],[],True)
    assert result['route']=='SYSTEM' and result['questions']==[]
    assert '红冲' in result['explanation'] and '缺资料' not in result['next_action']
    assert t==before


def test_missing_currency_is_system_evidence_gap_not_customer_upload():
    checks=[{'fact_id':'f','status':'BLOCKED','codes':['CURRENCY_SOURCE_MISSING'],
             'message':'当前提取结果缺少币种来源'}]
    result=classify_task(task(),[row()],checks,True)
    assert result['route']=='SYSTEM' and result['questions']==[]
    assert '币种' in result['explanation'] and not result['human_ready']


def test_real_offset_mismatch_has_specific_business_question():
    checks=[{'fact_id':'f','status':'BLOCKED','codes':['AMOUNT_CANCELLATION_MISMATCH'],
             'message':'蓝红票金额未抵消'}]
    result=classify_task(task(),[row()],checks,True)
    assert result['route']=='HUMAN' and '红票' in result['questions'][0]
    assert result['human_ready']


def test_system_evidence_gap_precedes_alleged_mismatch():
    checks=[{'fact_id':'f','status':'BLOCKED','codes':['AMOUNT_SOURCE_MISSING','AMOUNT_CANCELLATION_MISMATCH'],'message':'来源不完整'}]
    assert classify_task(task(),[row()],checks,True)['route']=='SYSTEM'


def test_invalid_amount_with_source_value_goes_to_system_first():
    r=row('expense','总支出笔数',None,'DIFFERENT')
    assert classify_task(task(reason='支出金额：金额格式无效',field='expense'),[r],[],True)['route']=='SYSTEM'


def test_unknown_rule_or_unlocated_record_is_not_human_ready():
    assert classify_task(task(reason='新规则：无法判断',field='new'),[row()],[],True)['route']=='SYSTEM'
    r=row();r['source_anchor']={}
    assert classify_task(task(),[r],[],True)['route']=='SYSTEM'


def test_identified_invoice_with_located_blank_date_is_a_real_evidence_gap():
    r=row('invoice_date',None,None,'MISSING');r['values']={'invoice_no':'123'}
    t=task(reason='开票日期：日期缺失或不能确定',field='invoice_date')
    result=classify_task(t,[r],[],True)
    assert result['route']=='HUMAN' and '单元格为空' in result['explanation']
    r['values']={}
    assert classify_task(t,[r],[],True)['route']=='SYSTEM'  # an unidentified/summary row is not a missing invoice


def test_clear_period_and_bill_business_questions_remain_actionable():
    r=row('transaction_date','2026-02-02','2026-02-02','DIRECT_MATCH')
    t=task(reason='业务期间：不属于已核定的本期业务范围，需核对原件与业务日期',field='transaction_date')
    assert classify_task(t,[r],[],True)['route']=='HUMAN'
    t=task('BILL',reason='业务期间：票据清单未列本期收付日期及业务角色',field='period');t['descriptor']['options']=[{'id':'confirm_bill_business','available':True}]
    r=row('period',None,None,'MISSING')
    assert classify_task(t,[r],[],True)['route']=='HUMAN'


def test_parse_failure_and_invalid_source_never_request_customer_evidence():
    assert classify_task(task('PARSE'),[],[],True)['route']=='SYSTEM'
    assert classify_task(task(),[row()],[],False)['route']=='SYSTEM'


def test_bank_ownership_can_be_confirmed_without_claiming_it_was_extracted():
    t=task(reason='bank_account_ref：请确认流水所属的企业账户',field='account_number')
    t['descriptor']['options']=[{'id':'confirm_statement_account','available':True}]
    r=row('account_number',None,'candidate','UNLOCATED')
    assert classify_task(t,[r],[],True)['route']=='HUMAN'
    r['comparison'][0]['state']='DIFFERENT'
    assert classify_task(t,[r],[],True)['route']=='SYSTEM'


def test_existing_bill_opinion_and_account_gap_remain_business_not_parser_work():
    t=task('BILL',reason='业务期间：票据归属待确认',field='period')
    t['descriptor']['options']=[{'id':'confirm_bill_business','available':False},
                              {'id':'supplement','available':True}]
    r=row('period',None,None,'MISSING');r['bill_confirmation']={'status':'OPINION'}
    q=classify_task(t,[r],[],True)
    assert q['route']=='HUMAN' and '撤销' in q['questions'][0]
    t['kind']='BILL_ACCOUNT';r['bill_confirmation']['status']='CONFIRMED'
    q=classify_task(t,[r],[],True)
    assert q['route']=='HUMAN' and '科目' in q['questions'][0]
    assert t['descriptor']['options'][0]['available'] is False


def test_currency_source_audit_does_not_apply_candidates(client):
    import hashlib
    from test_tabular_ingestion import xlsx_fixture
    svc=client.app.state.service
    content=xlsx_fixture([('数据',[['币种：人民币','金额'],['',100]])])
    path=svc.store.database.settings.storage_path/'currency.xlsx';path.write_bytes(content)
    artifact={'object_id':'source','version':2,'data':{'storage_path':'currency.xlsx','sha256':hashlib.sha256(content).hexdigest()}}
    before=deepcopy(artifact)
    audit=svc.problem_review.currency_source_audit(artifact)
    assert audit['status']=='CANDIDATES_FOUND' and audit['candidates'][0]['region']=='数据!A1'
    assert artifact==before and path.read_bytes()==content
    artifact['data']['sha256']='0'*64
    assert svc.problem_review.currency_source_audit(artifact)['status']=='UNREADABLE'


def test_routing_preserves_records_gates_and_review_history(client,scope):
    from test_invoice_amount_review import setup_invoices
    from app.ontology.contracts import Scope
    svc=client.app.state.service;s=Scope(**scope)
    setup_invoices(client,scope)
    original=svc.workbench(s,_problem_review=False)
    before=svc.store.list_objects(None,s)
    projected=svc.workbench(s)
    assert svc.store.list_objects(None,s)==before
    assert projected['material_review']['records']==original['material_review']['records']
    for key in ('baseline','data_readiness','groups','vouchers','invoice_amount_review'):
        assert projected[key]==original[key]
    counts=projected['material_review']['counts']
    assert counts['human_issue_tasks']+counts['system_issue_tasks']==counts['issue_tasks']
    assert {t['id'] for t in projected['material_review']['tasks']}=={t['id'] for t in original['material_review']['tasks']}
    assert [t['descriptor'] for t in projected['material_review']['tasks']]==[t['descriptor'] for t in original['material_review']['tasks']]


def test_zero_data_routing_is_readonly(client,scope):
    from app.ontology.contracts import Scope
    svc=client.app.state.service;s=Scope(**scope);svc.create_scope(s)
    before=svc.store.list_objects(None,s)
    m=svc.workbench(s)['material_review']
    assert m['counts']['human_issue_tasks']==m['counts']['system_issue_tasks']==0
    assert m['tasks']==[] and svc.store.list_objects(None,s)==before
