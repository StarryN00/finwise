from copy import deepcopy
from decimal import Decimal

import pytest

from app.bookkeeping_profile import snapshot, profile_contract
from app.reimbursements import reimbursement_errors, reimbursement_reviewed
from app.travel_policy import travel_policy_errors
from app.autonomous_runtime import prepare
from app.config import Settings
from test_autonomous_workflow import setup


def fixture(person='张三', opening='0.00', invoice='240.00', payment='266.00', code='224101'):
    ref = lambda sheet, row: dict(source_id='s', sheet=sheet, row=row)
    i, b, a = ref('票据', 2), ref('银行', 2), ref('余额及科目', 2)
    rows = []
    def line(voucher, account, name, debit, credit, source):
        rows.append(dict(voucher=voucher, date='2026-08-31', code=account, name=name, memo='报销',
                         debit=debit, credit=credit, source=source))
    if invoice:
        line('I1','560205','差旅费',invoice,'0.00',i)
        line('I1',code,'其他应付款—'+person,'0.00',invoice,i)
    if payment:
        line('P1',code,'其他应付款—'+person,payment,'0.00',b)
        line('P1','1002','银行存款','0.00',payment,b)
    balance=Decimal(opening)
    account=dict(id='ER-'+person,person=person,account_code=code,account_name='其他应付款—'+person,
        account_evidence=[a],opening_balance=opening,opening_evidence=[a],
        invoices=[dict(source=i,voucher='I1',ownership_evidence=[i])] if invoice else [],
        payments=[dict(source=b,voucher='P1',ownership_evidence=[b])] if payment else [],
        closing_balance=f'{balance+Decimal(invoice or 0)-Decimal(payment or 0):.2f}')
    delivery=dict(entries=rows,opening=[dict(code=code,name=account['account_name'],debit=f'{max(-balance,0):.2f}',credit=f'{max(balance,0):.2f}',source=a)],
        bank=[dict(source=b,income='0.00',expense=payment,counterparty=person)] if payment else [],
        invoices=[dict(source=i,number='T1',gross=invoice,net=invoice,tax='0.00',kind='进项')] if invoice else [],
        findings=[],employee_reimbursements=[account],unassigned_reimbursement_invoices=[],
        voucher_assessments=[dict(voucher=v,status='READY_FOR_REVIEW',finding_ids=[]) for v in ['I1','P1'] if any(e['voucher']==v for e in rows)])
    return delivery,dict(bookkeeping_profile=snapshot(),statements=[])


@pytest.mark.parametrize('opening,invoice,payment,expected',[
    ('0.00','240.00','266.00','-26.00'), ('0.00','1000.00','800.00','200.00'),
    ('0.00','1000.00','1000.00','0.00'), ('-26.00','26.00',None,'0.00'),
    ('200.00',None,'200.00','0.00'), ('0.00',None,'1200.00','-1200.00'),
    ('0.00','1200.00',None,'1200.00'),
])
def test_separate_invoice_payment_and_cross_month_open_balance(opening,invoice,payment,expected):
    d,c=fixture(opening=opening,invoice=invoice,payment=payment)
    assert not reimbursement_errors(d,c)
    assert d['employee_reimbursements'][0]['closing_balance']==expected
    assert not d['findings']


@pytest.mark.parametrize('tamper', ['wrong-sign','guessed-opening','direct-expense','other-person',
    'same-invoice-twice','same-invoice-number','same-payment-twice','shared-person-account','no-owner-evidence',
    'foreign-evidence','net-instead-of-gross','missing-register','unbalanced-payable'])
def test_invalid_reimbursement_never_becomes_ready(tamper):
    d,c=fixture();a=d['employee_reimbursements'][0]
    if tamper=='wrong-sign':a['closing_balance']='26.00'
    elif tamper=='guessed-opening':a['opening_balance']='100.00';a['closing_balance']='74.00'
    elif tamper=='direct-expense':d['entries'][2]['code']='560205'
    elif tamper=='other-person':d['bank'][0]['counterparty']='李四'
    elif tamper=='same-invoice-twice':a['invoices']*=2
    elif tamper=='same-payment-twice':a['payments']*=2
    elif tamper=='shared-person-account':
        other=deepcopy(a);other.update(id='ER-李四',person='李四');d['employee_reimbursements'].append(other)
    elif tamper=='no-owner-evidence':a['invoices'][0]['ownership_evidence']=[]
    elif tamper=='foreign-evidence':a['account_evidence'][0]['source_id']='other-enterprise'
    elif tamper=='net-instead-of-gross':d['invoices'][0].update(net='226.42',tax='13.58',gross='226.42')
    elif tamper=='missing-register':d.pop('employee_reimbursements')
    elif tamper=='unbalanced-payable':d['entries'][2]['debit']='240.00'
    elif tamper=='same-invoice-number':
        other=deepcopy(d['invoices'][0]);other['source']['row']=3;d['invoices'].append(other)
        a['invoices'].append(dict(source=other['source'],voucher='I1',ownership_evidence=[other['source']]))
    assert reimbursement_errors(d,c,lambda r:r['source_id']=='s')


def test_two_people_cannot_offset_each_others_balances():
    d,c=fixture(invoice='240.00',payment=None)
    e,_=fixture(person='李四',invoice=None,payment='266.00',code='224102')
    for key in ('entries','opening','bank','invoices','employee_reimbursements','voucher_assessments'):
        d[key].extend(e[key])
    assert not reimbursement_errors(d,c)
    assert [a['closing_balance'] for a in d['employee_reimbursements']]==['240.00','-266.00']
    d['employee_reimbursements'][0]['closing_balance']='-26.00'
    assert reimbursement_errors(d,c)


def test_balanced_but_fabricated_source_amounts_rejected():
    d,c=fixture()
    tables={'s':{'票据':[dict(row=2,values=['票据真实金额',230,0,230])],
                 '银行':[dict(row=2,values=['付款',266,0])],
                 '余额及科目':[dict(row=2,values=['224101','张三',0,0])]}}
    assert any('票据金额与原件' in e for e in reimbursement_errors(d,c,tables=tables))
    tables['s']['票据'][0]['values']=[240,0,240]
    assert not reimbursement_errors(d,c,tables=tables)
    tables['s']['银行'][0]['values']=[267,0]
    assert any('付款金额与原件' in e for e in reimbursement_errors(d,c,tables=tables))


def test_unassigned_ticket_does_not_block_known_person_payment_or_create_expense():
    d,c=fixture(invoice=None)
    source=dict(source_id='s',sheet='票据',row=3)
    d['invoices']=[dict(source=source,number='unknown',net='50.00',tax='0.00',gross='50.00')]
    d['findings']=[dict(id='F1',needs_user=True,affected_vouchers=[],evidence=[source])]
    d['unassigned_reimbursement_invoices']=[dict(id='UI1',source=source,finding_id='F1')]
    assert not reimbursement_errors(d,c)
    assert all(a['status']=='READY_FOR_REVIEW' for a in d['voucher_assessments'])
    assert reimbursement_reviewed(d,dict(reviewed_employee_reimbursements=['ER-张三','UI1']),c)
    assert not reimbursement_reviewed(d,dict(reviewed_employee_reimbursements=['ER-张三']),c)
    d['employee_reimbursements'][0]['invoices']=[dict(source=source,voucher='P1',ownership_evidence=[source])]
    assert reimbursement_errors(d,c)


def test_real_delegate_evidence_keeps_both_person_and_payee():
    d,c=fixture();d['bank'][0]['counterparty']='代收人'
    assert reimbursement_errors(d,c)
    d['employee_reimbursements'][0]['payments'][0]['ownership_evidence'].append(dict(source_id='s',sheet='委托说明',row=2))
    assert not reimbursement_errors(d,c)
    assert d['bank'][0]['counterparty']=='代收人'


def test_user_can_assign_previously_unknown_invoice_without_fabricating_original_evidence():
    d,c=fixture();item=d['employee_reimbursements'][0]['invoices'][0]
    item.update(ownership_evidence=[],ownership_answer_ids=['answer'])
    c['statements']=[dict(answer_id='answer',kind='FREE_TEXT',text='T1票据由张三报销',evidence=[item['source']],affected_vouchers=[])]
    assert not reimbursement_errors(d,c)
    c['statements'][0]['kind']='MATERIALS_COMPLETE'
    assert reimbursement_errors(d,c)
    c['statements'][0].update(kind='INVOICE_MATCH_SELECTION',note='')
    assert reimbursement_errors(d,c)
    c['statements'][0].update(kind='FREE_TEXT',evidence=[])
    assert reimbursement_errors(d,c)


def test_reimbursement_replaces_exact_travel_matching_only_in_simple_mode():
    d,c=fixture();c['travel_policy']=dict(id='policy',version=1)
    d['travel_policy_applications']=[dict(id='TP1',policy_id='policy',policy_version=1,voucher='P1',kind='TRAVEL',
        reason='真实个人报销付款先结往来',evidence=[d['bank'][0]['source']],settlement_match_ids=[],manual_reasons=[],confirmed_reasons=[],finding_ids=[])]
    assert not travel_policy_errors(d,c)
    original=deepcopy(c);original['bookkeeping_profile']=snapshot(dict(version=1,data=dict(mode='ORIGINAL')))
    assert travel_policy_errors(d,original)
    assert reimbursement_errors(d,original)
    d['travel_policy_applications'][0]['kind']='LOAN_OFFSET'
    assert travel_policy_errors(d,c)  # Policy is not personal-loan cancellation consent.


def test_sandbox_and_host_share_signed_balance_and_evidence_checks(tmp_path):
    from pathlib import Path
    d,c=fixture()
    settings=Settings(root=Path(__file__).resolve().parents[1],database_path=tmp_path/'db.sqlite',storage_path=tmp_path/'sources')
    root,_=prepare(tmp_path/'run',dict(sources=[]),{},c,settings)
    ns={};exec((root/'tools/checker.py').read_text(),ns)
    assert not ns['reimbursement_errors'](d,c)
    d['employee_reimbursements'][0]['closing_balance']='26.00'
    assert ns['reimbursement_errors'](d,c)==reimbursement_errors(d,c)
    assert '个人报销往来（合同 v12' in (root/'CONTRACT.md').read_text()
    assert '个人报销往来（合同 v12' not in profile_contract(snapshot(dict(version=1,data=dict(mode='ORIGINAL'))))


@pytest.mark.parametrize('tamper',['missing-review','missing-register','unknown-review-id'])
def test_host_rejects_even_a_claimed_pass_review(setup,tamper):
    _,service,scope,_,mature,result=setup
    def runner(*args):
        r=result()
        if tamper=='missing-review':r['review'].pop('reviewed_employee_reimbursements')
        elif tamper=='missing-register':r['delivery'].pop('employee_reimbursements')
        else:r['review']['reviewed_employee_reimbursements']=['fake-person']
        return r
    service.autonomous.runner=runner;mature()
    assert not service.autonomous.tick(scope)
    assert not service.store.list_objects('VoucherVersion',scope)


def test_fabricated_employee_account_cannot_cite_expense_or_parent_row():
    d,c=fixture()
    tables={'s':{'余额及科目':[dict(row=2,values=['560205','差旅费',0,0])]}}
    assert any('科目编码及姓名' in e for e in reimbursement_errors(d,c,tables=tables))
    tables['s']['余额及科目'][0]['values']=['2241','其他应付款',0,0]
    assert any('科目编码及姓名' in e for e in reimbursement_errors(d,c,tables=tables))


def test_personal_payment_does_not_keep_old_matching_gate_or_omit_unknown_tickets():
    d,c=fixture(invoice=None)
    ref=dict(source_id='s',sheet='票据',row=3)
    d['invoices']=[dict(source=ref,number='unknown',net='50.00',tax='0.00',gross='50.00')]
    d['findings']=[dict(id='F1',needs_user=True,blocks_confirmation=True,evidence=[ref],
        invoice_matching=dict(state='CANDIDATE',payment_sources=[d['bank'][0]['source']],candidate_invoice_sources=[ref]))]
    errors=reimbursement_errors(d,c)
    assert any('不能遗漏归属' in e for e in errors)
    assert any('不能继续被逐笔配票' in e for e in errors)
    d['unassigned_reimbursement_invoices']=[dict(id='UI1',source=ref,finding_id='F1')]
    d['findings'][0]['blocks_confirmation']=False
    assert not reimbursement_errors(d,c)
