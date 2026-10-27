"""Matching states, immutable selections, scope/version guards and atomic batches."""
from copy import deepcopy
from fastapi.testclient import TestClient
import pytest

from app.invoice_matching import invoice_matching_errors, matching_projection
from app.review_loop import review_loop_approved
from test_autonomous_workflow import setup


def matching_result(base, source, statements=()):
    result = base(); d = result['delivery']; sid = source['object_id']
    ref = lambda sheet, row: {'source_id': sid, 'sheet': sheet, 'row': row}
    payment, second = ref('Bank', 2), ref('Bank', 3)
    invoices = [ref('Invoices', 2), ref('Invoices', 3)]
    d['bank'] = [dict(source=r, date='2026-03-01', income='0.00', expense=amount, counterparty='张三', memo='差旅费')
                 for r, amount in [(payment, '266.00'), (second, '100.00')]]
    d['invoices'] = [dict(source=r, number=f'票{i}', date='2026-02-28', gross=amount, net=amount, tax='0.00', kind='进项')
                     for i, (r, amount) in enumerate(zip(invoices, ['123.00', '117.00']), 1)]
    d['findings'] = []
    d['voucher_assessments'] = []
    d['entries'] = []
    for number, bank in [('候选001', d['bank'][0]), ('候选002', d['bank'][1])]:
        for code, name, debit, credit in [('6602', '管理费用', bank['expense'], '0.00'), ('1002', '银行存款', '0.00', bank['expense'])]:
            d['entries'].append(dict(voucher=number, date=bank['date'], code=code, name=name, memo='测试报销', debit=debit, credit=credit, source=bank['source']))
        fid = 'match-' + number
        item = dict(state='CANDIDATE' if number=='候选001' else 'MISSING', payment_sources=[bank['source']],
                    candidate_invoice_sources=invoices if number=='候选001' else [], confirmed_invoice_sources=[],
                    reason='归属待核实' if number=='候选001' else '未找到对应票据', confirmation_evidence=[], answer_ids=[])
        f = dict(id=fid, title='报销票款待匹配', detail='资金记录已确认，票据归属仍需核实。', needs_user=True,
                 blocks_confirmation=True, affected_vouchers=[number], evidence=[bank['source'], *invoices], invoice_matching=item,
                 request=dict(question='哪些票据属于这笔款项？', why_needed='决定报销组成', can_continue='已确认付款', evidence_request='选择票据', scope='PERIOD'))
        d['findings'].append(f)
        d['voucher_assessments'].append(dict(voucher=number, status='NEEDS_EVIDENCE', reason='票款未确认', finding_ids=[fid], evidence=f['evidence'], bookkeeping_profile=d['bookkeeping_profile']))
    d['settlement_matches'] = [dict(id='m1', basis='GROSS', status='CANDIDATE', payment_source=payment,
                                  invoice_sources=invoices, other_components=[], affected_vouchers=['候选001'],
                                  finding_ids=['match-候选001'], reason='车票为候选，未确认归属')]
    d['decision_responses'] = [dict(answer_id=a['answer_id'], outcome='PARTIAL', explanation='已记录票据归属；差额仍需核实', affected_vouchers=a['affected_vouchers']) for a in statements]
    result['review'].update(ready_vouchers=[], reviewed_decisions=[], reviewed_settlement_matches=['m1'],
                           reviewed_responses=[a['answer_id'] for a in statements], reviewed_invoice_matching=[f['id'] for f in d['findings']])
    return result


def accepted(setup):
    app, service, scope, source, mature, base = setup
    service.autonomous.runner = lambda *args: matching_result(base, source)
    mature(); assert service.autonomous.tick(scope)
    job = service.autonomous.current(scope)
    return TestClient(app), service, scope, job


def test_candidate_totals_never_become_a_confirmed_gap(setup):
    _, _, _, source, _, base = setup
    result = matching_result(base, source); d = result['delivery']
    assert not invoice_matching_errors(d, {'review_loop_version':8})
    p = matching_projection(d)
    assert p['items'][0]['candidate_total']=='240.00'
    assert p['items'][0]['difference'] is None
    assert p['items'][1]['state']=='MISSING'
    # Equal amounts still leave ownership unresolved.
    d['bank'][0]['expense']='240.00'
    assert matching_projection(d)['items'][0]['state']=='CANDIDATE'
    assert not invoice_matching_errors(d, {'review_loop_version':8})


@pytest.mark.parametrize('mutation', ['missing-with-tickets','gap-with-candidates','confirmed-without-evidence','invalid-source','duplicate-source','unclassified','hidden-options'])
def test_invalid_or_guessed_matching_rejected(setup, mutation):
    _, _, _, source, _, base = setup
    d=matching_result(base, source)['delivery']; f=d['findings'][0]; m=f['invoice_matching']
    if mutation=='missing-with-tickets': m['state']='MISSING'
    elif mutation=='gap-with-candidates': m['state']='AMOUNT_DIFFERENCE'
    elif mutation=='confirmed-without-evidence':
        m['state']='AMOUNT_DIFFERENCE'; m['confirmed_invoice_sources']=m['candidate_invoice_sources']; m['candidate_invoice_sources']=[]
    elif mutation=='invalid-source': m['payment_sources'][0]={**m['payment_sources'][0], 'source_id':'other-company'}
    elif mutation=='duplicate-source': m['candidate_invoice_sources']*=2
    elif mutation=='unclassified': f.pop('invoice_matching')
    elif mutation=='hidden-options': f['decision']={'question':'差额是补贴吗？','options':[]}
    assert invoice_matching_errors(d, {'review_loop_version':8})


def test_confirmed_gap_requires_evidence_and_independent_coverage(setup):
    _, _, _, source, _, base = setup
    result=matching_result(base, source);d=result['delivery'];f=d['findings'][0];m=f['invoice_matching']
    m.update(state='AMOUNT_DIFFERENCE', confirmed_invoice_sources=m['candidate_invoice_sources'], candidate_invoice_sources=[], confirmation_evidence=f['evidence'])
    assert not invoice_matching_errors(d, {'review_loop_version':8})
    assert matching_projection(d)['items'][0]['difference']=='26.00'
    assert matching_projection(d)['invoices'][0]['used_by']==['候选001']
    assert review_loop_approved(d, result['review'])
    result['review'].pop('reviewed_invoice_matching')
    assert not review_loop_approved(d, result['review'])


def test_selection_cannot_confirm_unselected_invoices(setup):
    _, _, _, source, _, base = setup
    d=matching_result(base,source)['delivery'];m=d['findings'][0]['invoice_matching']
    m.update(state='AMOUNT_DIFFERENCE',confirmed_invoice_sources=m['candidate_invoice_sources'],candidate_invoice_sources=[],answer_ids=['a'])
    answer=dict(answer_id='a',kind='INVOICE_MATCH_SELECTION',affected_vouchers=['候选001'],note='',
                invoice_selection={'invoices':[d['invoices'][0]]})
    ctx={'review_loop_version':8,'statements':[answer]}
    assert any('实际选择' in e for e in invoice_matching_errors(d,ctx))
    answer['invoice_selection']['invoices']=d['invoices']
    assert not invoice_matching_errors(d,ctx)


def test_batch_selection_records_snapshots_once_and_invalidates_old_input(setup):
    client, service, scope, job=accepted(setup)
    before=deepcopy(job)
    p=service.workbench(scope)['autonomous_workflow']['invoice_matching']
    items=[dict(finding_id=p['items'][0]['finding_id'], invoice_ids=[i['id'] for i in p['invoices']], note=''),
           dict(finding_id=p['items'][1]['finding_id'], invoice_ids=[], note='这笔票据尚未提供')]
    body=dict(scope=scope.model_dump(), run_id=job['object_id'], items=items, acknowledged=True)
    response=client.post('/api/v1/autonomous/invoice-matching',json=body)
    assert response.status_code==200,response.text
    answers=service.store.list_objects('AutonomousAnswer',scope)
    assert len(answers)==2
    a=next(a['data'] for a in answers if a['data']['invoice_selection']['action']=='CONFIRM_INVOICES')
    assert a['kind']=='INVOICE_MATCH_SELECTION' and a['evidence_kind']=='USER_STATEMENT'
    assert [i['gross'] for i in a['invoice_selection']['invoices']]==['123.00','117.00']
    assert a['invoice_selection']['payments'][0]['expense']=='266.00'
    assert service.autonomous.current(scope)['data']['revision']==job['data']['revision']+1
    assert service.store.get_object(job['object_id'],scope)==before
    assert client.post('/api/v1/autonomous/invoice-matching',json=body).status_code==409
    assert len(service.store.list_objects('AutonomousAnswer',scope))==2


@pytest.mark.parametrize('bad', ['viewer','unacknowledged','forged-invoice','foreign-scope','empty','duplicate-task','injected-snapshot'])
def test_matching_api_guards_and_batch_rollback(setup,bad):
    client, service, scope, job=accepted(setup)
    body=dict(scope=scope.model_dump(),run_id=job['object_id'],acknowledged=True,
              items=[dict(finding_id='match-候选001',invoice_ids=[],note='实际票据另行提供')])
    headers={};expected=409
    if bad=='viewer': headers={'X-Role':'viewer'};expected=403
    elif bad=='unacknowledged':body['acknowledged']=False
    elif bad=='forged-invoice':body['items'].append(dict(finding_id='match-候选002',invoice_ids=['forged'],note=''))
    elif bad=='foreign-scope':body['scope']['legal_entity_id']='different';expected=409
    elif bad=='empty':body['items'][0]['note']=' '
    elif bad=='duplicate-task':body['items']*=2
    elif bad=='injected-snapshot':body['items'][0]['invoices']=[{'gross':'266.00'}];expected=422
    r=client.post('/api/v1/autonomous/invoice-matching',json=body,headers=headers)
    assert r.status_code==expected,r.text
    assert not service.store.list_objects('AutonomousAnswer',scope)
    assert service.autonomous.current(scope)['object_id']==job['object_id']


def test_authenticated_matching_scope_and_actor_are_server_owned(setup):
    from dataclasses import replace
    from app.auth import create_user, grant_scope
    from test_scope_provisioning import login
    _, service, scope, job=accepted(setup)
    app=setup[0];app.state.settings=replace(app.state.settings, require_auth=True)
    create_user(app.state.database,'alice','matching-test-password','accountant')
    grant_scope(app.state.database,'alice',scope)
    client,headers=login(app,'alice','matching-test-password')
    body=dict(scope=scope.model_dump(),run_id=job['object_id'],acknowledged=True,
              items=[dict(finding_id='match-候选001',invoice_ids=[],note='另有报销单，稍后补充')])
    foreign={**body,'scope':{**body['scope'],'legal_entity_id':'other-enterprise'}}
    assert client.post('/api/v1/autonomous/invoice-matching',json=foreign,headers=headers).status_code==403
    assert client.post('/api/v1/autonomous/invoice-matching',json=body).status_code==403
    response=client.post('/api/v1/autonomous/invoice-matching',json=body,headers={**headers,'X-Actor-Id':'forged'})
    assert response.status_code==200,response.text
    assert service.store.list_objects('AutonomousAnswer',scope)[0]['data']['author']=='alice'
