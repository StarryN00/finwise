from pathlib import Path
import json
import pytest
from app import autonomous_runtime as runtime
from app.autonomous_checks import validate
from app.stage23_pilot import write_json
from app.config import Settings


def test_source_bookkeeping_checks_balance_and_original_anchors(tmp_path):
    import openpyxl
    from app.stage23_pilot import sha256
    b=openpyxl.Workbook();b.active.append(['service fee',10]);p=tmp_path/'source.xlsx';b.save(p)
    m={'period':'2026-08','sources':[{'id':'s','path':'source.xlsx','sha256':sha256(p)}]}
    ref={'source_id':'s','sheet':'Sheet','row':1}
    d={'period':'2026-08','mode':'SOURCE_BOOKKEEPING','source_roles':{'s':'流水'},'entries':[
      {'voucher':'001','date':'2026-08-01','code':'6603','name':'财务费用','debit':'10.00','credit':'0.00','source':ref},
      {'voucher':'001','date':'2026-08-01','code':'1002','name':'银行存款','debit':'0.00','credit':'10.00','source':ref}],
       'findings':[],'voucher_assessments':[{'voucher':'001','status':'READY_FOR_REVIEW','reason':'手续费回单','evidence':[ref]}], 'report':'范围限制与处理结论。'*20}
    assert validate(tmp_path,m,d,{})['passed']
    d['entries'][1]['date']='2026-08-02'
    outcome=validate(tmp_path,m,d,{})
    assert not outcome['passed'] and '001凭证日期一致' in outcome['errors']
    d['entries'][1]['date']='2026-08-01'
    d['entries'][0]['debit']='11.00';assert not validate(tmp_path,m,d,{})['passed']
    d['entries'][0]['debit']='10.00';d['entries'][0]['source']={**ref,'row':5}
    assert not validate(tmp_path,m,d,{})['passed']


@pytest.mark.parametrize('review_path', ['work/review.json', 'review.json'])
def test_review_rejection_auto_repairs_and_nonbank_pdf_does_not_use_bank_ocr(tmp_path,monkeypatch,review_path):
    root=Path(__file__).resolve().parents[1]
    assert '前期序时账' in runtime.CONTRACT_V2 and '账内未见' in runtime.CONTRACT_V2
    settings=Settings(root=root,database_path=tmp_path/'db',storage_path=tmp_path/'data')
    source=tmp_path/'contract.pdf';source.write_bytes(b'%PDF-test')
    from app.stage23_pilot import sha256
    m={'period':'2026-08','sources':[{'id':'contract','filename':'contract.pdf','path':'sources/contract.pdf','sha256':sha256(source)}]}
    calls=[]
    def execute(workspace,prompt,log_base,settings,heartbeat):
        calls.append(log_base.name)
        if log_base.name.startswith('worker'):
            write_json(workspace/'work/delivery.json',{'bank':[],'voucher_assessments':[]})
            (workspace/'work/plan.md').write_text('plan');(workspace/'work/process.md').write_text('process')
        else:
            assert '历史已回答方案' in prompt
            assert '"reviewed_decisions": []' in prompt
            assert '唯一输出位置是 work/review.json' in prompt
            write_json(workspace/review_path,{'verdict':'needs_revision' if log_base.name=='reviewer-1' else 'pass',
                'defects':[{'detail':'遗漏业务'}] if log_base.name=='reviewer-1' else [],
                'coverage':[{'area':'合同','conclusion':'复算通过','evidence':[{'source_id':'contract','page':1}]}],'ready_vouchers':[]})
    monkeypatch.setattr(runtime,'execute',execute)
    monkeypatch.setattr(runtime,'validate',lambda *_:{'passed':True,'errors':[]})
    def forbidden(*_):raise AssertionError('普通合同不得使用银行专用OCR')
    monkeypatch.setattr('app.local_pdf_ocr.read_statement',forbidden)
    r=runtime.run(tmp_path/'run',m,{'contract':source},{},settings,lambda:None,lambda *_:None)
    assert r['rounds']==2 and calls==['worker-1','reviewer-1','worker-2','reviewer-2']
    assert (tmp_path/'run/executor/work/review-feedback.json').is_file()


def test_conflicting_review_outputs_are_returned_for_repair(tmp_path,monkeypatch):
    settings=Settings(root=Path(__file__).resolve().parents[1],database_path=tmp_path/'db',storage_path=tmp_path/'data',autonomous_max_rounds=1)
    def execute(workspace,prompt,log_base,settings,heartbeat):
        if log_base.name.startswith('worker'):
            write_json(workspace/'work/delivery.json',{'bank':[],'voucher_assessments':[]})
        else:
            review={'verdict':'pass','defects':[],'coverage':[{'area':'原件','conclusion':'复算通过','evidence':[{'source_id':'s','row':1}]}],'ready_vouchers':[]}
            write_json(workspace/'work/review.json',review)
            write_json(workspace/'review.json',{**review,'verdict':'needs_revision'})
    monkeypatch.setattr(runtime,'execute',execute)
    monkeypatch.setattr(runtime,'validate',lambda *_:{'passed':True,'errors':[]})
    with pytest.raises(RuntimeError,match='轮次上限'):
        runtime.run(tmp_path/'run',{'period':'2026-08','sources':[]},{},{},settings,lambda:None,lambda *_:None)
    feedback=json.loads((tmp_path/'run/failure.json').read_text())
    assert '内容冲突' in feedback['independent_review']['defects'][0]['detail']
    assert not (tmp_path/'run/accepted.json').exists()


@pytest.mark.parametrize('contents', ['[]', 'invalid'])
def test_invalid_review_is_not_accepted(tmp_path,contents):
    (tmp_path/'work').mkdir()
    (tmp_path/'work/review.json').write_text(contents)
    with pytest.raises(ValueError):
        runtime.read_review(tmp_path)


def test_structured_review_references_preserve_explanations(tmp_path):
    references = {'reviewed_decisions':[{'id':'F01','verdict':'ok','note':'Checked against source'}],
        'reviewed_responses':[{'answer_id':'a1','outcome_check':'Applied correctly'}],
        'reviewed_settlement_matches':[{'id':'s1','verdict':'pass'}]}
    write_json(tmp_path/'work/review.json',{'verdict':'pass',**references})
    review = runtime.read_review(tmp_path)
    assert review['reviewed_decisions'] == ['F01']
    assert review['reviewed_responses'] == ['a1']
    assert review['reviewed_settlement_matches'] == ['s1']
    assert review['structured_reference_details'] == references


@pytest.mark.parametrize('values', [[{'wrong_key':'F01'}], [{'id':'F01','verdict':'needs_revision'}],
                                  [{'id':'F01','verdict':[]}],
                                  [{'id':'F01'}, 'F01'], [[]], [None], {'id':'F01'}])
def test_invalid_structured_references_are_rejected_for_repair(tmp_path, values):
    from app.review_loop import review_loop_approved
    write_json(tmp_path/'work/review.json',{'verdict':'pass','reviewed_decisions':values})
    with pytest.raises(ValueError):
        runtime.read_review(tmp_path)
    assert not review_loop_approved({}, {'reviewed_decisions':values})


def test_completed_candidate_resumes_at_fresh_validation_and_review(tmp_path, monkeypatch):
    from dataclasses import replace
    settings=Settings(root=Path(__file__).resolve().parents[1],database_path=tmp_path/'db',storage_path=tmp_path/'data')
    manifest={'period':'2026-08','sources':[]}
    old,_=runtime.prepare(tmp_path/'old',manifest,{}, {},settings)
    write_json(old/'work/delivery.json',{'bank':[],'voucher_assessments':[]})
    write_json(tmp_path/'old/mechanical-1.json',{'passed':True})
    write_json(old/'work/review.json',{'verdict':'pass'})  # This is never used as current approval.
    calls=[]
    def execute(w,p,l,s,h):
        calls.append(l.name)
        assert l.name.startswith('reviewer')
        assert '字符串编号数组' in p
        write_json(w/'work/review.json',{'verdict':'pass','defects':[],
            'coverage':[{'area':'originals','conclusion':'Checked again','evidence':[{'source_id':'s','row':1}]}],
            'ready_vouchers':[]})
    validations=[]
    monkeypatch.setattr(runtime,'execute',execute)
    monkeypatch.setattr(runtime,'validate',lambda *args: validations.append(args) or {'passed':True,'errors':[]})
    result=runtime.run(tmp_path/'new',manifest,{}, {},replace(settings,autonomous_resume_from=tmp_path/'old'),lambda:None,lambda *_:None)
    assert result['review']['coverage'][0]['conclusion']=='Checked again'
    assert calls==['reviewer-1'] and len(validations)==1


def test_resumed_previous_pass_cannot_override_current_validation(tmp_path, monkeypatch):
    from dataclasses import replace
    settings=Settings(root=Path(__file__).resolve().parents[1],database_path=tmp_path/'db',storage_path=tmp_path/'data',autonomous_max_rounds=1)
    manifest={'period':'2026-08','sources':[]}
    old,_=runtime.prepare(tmp_path/'old',manifest,{}, {},settings)
    write_json(old/'work/delivery.json',{'bank':[],'voucher_assessments':[]})
    write_json(tmp_path/'old/mechanical-1.json',{'passed':True})
    def forbidden(*args):
        raise AssertionError('Invalid candidate must not reach a reviewer')
    monkeypatch.setattr(runtime,'execute',forbidden)
    monkeypatch.setattr(runtime,'validate',lambda *args: {'passed':False,'errors':['changed evidence']})
    with pytest.raises(RuntimeError,match='轮次上限'):
        runtime.run(tmp_path/'new',manifest,{}, {},replace(settings,autonomous_resume_from=tmp_path/'old'),lambda:None,lambda *_:None)
    assert not (tmp_path/'new/accepted.json').exists()
    assert 'changed evidence' in (tmp_path/'new/executor/work/review-feedback.json').read_text()


def test_saved_review_defects_resume_with_worker_repair(tmp_path):
    write_json(tmp_path/'executor/work/delivery.json',{})
    write_json(tmp_path/'mechanical-1.json',{'passed':True})
    assert runtime.has_checked_delivery(tmp_path,tmp_path/'executor')
    write_json(tmp_path/'executor/work/review-feedback.json',{'independent_review':{'verdict':'needs_revision'}})
    assert not runtime.has_checked_delivery(tmp_path,tmp_path/'executor')


def test_candidate_checkpoint_rejects_special_files(tmp_path):
    import os
    write_json(tmp_path/'executor/work/delivery.json',{})
    os.mkfifo(tmp_path/'mechanical-1.json')
    assert not runtime.has_checked_delivery(tmp_path,tmp_path/'executor')


def test_resume_preserves_work_but_requires_new_execution_and_review(tmp_path,monkeypatch):
    from dataclasses import replace
    settings=Settings(root=Path(__file__).resolve().parents[1],database_path=tmp_path/'db',storage_path=tmp_path/'data')
    manifest={'period':'2026-08','sources':[]}
    old,_=runtime.prepare(tmp_path/'old',manifest,{}, {},settings)
    (old/'work/plan.md').write_text('saved extraction')
    calls=[]
    def execute(w,p,l,s,h):
        calls.append(l.name)
        if l.name.startswith('worker'):
            assert '恢复同一资料版本' in p
            assert (w/'work/plan.md').read_text()=='saved extraction'
            write_json(w/'work/delivery.json',{'bank':[],'voucher_assessments':[]})
        else:
            write_json(w/'work/review.json',{'verdict':'pass','defects':[],
                'coverage':[{'area':'sources','conclusion':'checked','evidence':[{'source_id':'s','row':1}]}],'ready_vouchers':[]})
    monkeypatch.setattr(runtime,'execute',execute)
    monkeypatch.setattr(runtime,'validate',lambda *_:{'passed':True,'errors':[]})
    result=runtime.run(tmp_path/'new',manifest,{}, {},replace(settings,autonomous_resume_from=tmp_path/'old'),lambda:None,lambda *_:None)
    assert result['rounds']==1 and calls==['worker-1','reviewer-1']
    assert json.loads((tmp_path/'new/continuation.json').read_text())['requires_fresh_validation_and_review']


@pytest.mark.parametrize('damage',['frozen','symlink','period'])
def test_unsafe_or_different_checkpoint_is_rejected(tmp_path,damage):
    settings=Settings(root=Path(__file__).resolve().parents[1],database_path=tmp_path/'db',storage_path=tmp_path/'data')
    manifest={'period':'2026-08','sources':[]}
    old,_=runtime.prepare(tmp_path/'old',manifest,{}, {},settings)
    fresh,_=runtime.prepare(tmp_path/'new',manifest,{}, {},settings)
    if damage=='frozen':(old/'context.json').write_text('{"changed":true}')
    elif damage=='symlink':(old/'work/outside').symlink_to(tmp_path/'secret')
    else:manifest={**manifest,'period':'2026-09'}
    with pytest.raises(ValueError):runtime.restore_work(tmp_path/'old',fresh,manifest)


def test_independent_reviewer_cannot_rewrite_frozen_candidate(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[1];settings=Settings(root=root,database_path=tmp_path/'db',storage_path=tmp_path/'data')
    def execute(w,p,l,s,h):
        if l.name.startswith('worker'):write_json(w/'work/delivery.json',{'bank':[],'voucher_assessments':[]})
        else:
            (w/'candidate/delivery.json').write_text('{}')
            write_json(w/'review.json',{'verdict':'pass','defects':[],'coverage':[{}],'ready_vouchers':[]})
    monkeypatch.setattr(runtime,'execute',execute);monkeypatch.setattr(runtime,'validate',lambda *_:{'passed':True,'errors':[]})
    with pytest.raises(ValueError,match='冻结证据变化'):
        runtime.run(tmp_path/'run',{'period':'2026-08','sources':[]},{},{},settings,lambda:None,lambda *_:None)

def test_full_ledger_with_nonbank_supplement_keeps_bank_checks_scoped():
    from test_monthly_agent import validation_fixture
    from app.monthly_agent import validate_delivery
    d,tables=validation_fixture()
    assert validate_delivery(d,tables,{},'2026-08',set(d['source_roles']))['passed']
    d['source_roles']['contract']='补充合同，仅核实业务用途'
    r=validate_delivery(d,tables,{},'2026-08',set(d['source_roles']),bank_source_ids=set())
    assert r['passed'],r['errors']
    # An actual bank PDF still cannot bypass its dedicated evidence checks.
    assert not validate_delivery(d,tables,{},'2026-08',set(d['source_roles']),bank_source_ids={'contract'})['passed']


def test_confirmation_scope_and_minimal_request_are_checked(tmp_path):
    import openpyxl
    from app.stage23_pilot import sha256
    b=openpyxl.Workbook();b.active.append(['付款',10]);p=tmp_path/'source.xlsx';b.save(p)
    m={'period':'2026-08','sources':[{'id':'s','path':'source.xlsx','sha256':sha256(p)}]}
    ref={'source_id':'s','sheet':'Sheet','row':1}
    d={'period':'2026-08','mode':'SOURCE_BOOKKEEPING','source_roles':{'s':'银行'},'entries':[
      {'voucher':'001','date':'2026-08-01','code':'1123','name':'预付款','debit':'10.00','credit':'0.00','source':ref},
      {'voucher':'001','date':'2026-08-01','code':'1002','name':'银行','debit':'0.00','credit':'10.00','source':ref}],
      'findings':[{'id':'q','title':'验收','detail':'等待交付','needs_user':True,'evidence':[ref],'affected_vouchers':['001']}],
      'voucher_assessments':[{'voucher':'001','status':'READY_FOR_REVIEW','reason':'付款有据','evidence':[ref],'finding_ids':['q']}],
      'report':'有据付款，未来验收不能提前假定。'*20}
    assert not validate(tmp_path,m,d,{})['passed']
    f=d['findings'][0];f['blocks_confirmation']=False
    assert not validate(tmp_path,m,d,{})['passed']
    f['confirmation_reason']='当前只记录有据的付款与预付，验收仅影响未来转固'
    assert validate(tmp_path,m,d,{})['passed']
    f['request']={'question':'何时验收？'}
    assert not validate(tmp_path,m,d,{})['passed']
    f['request'].update(why_needed='决定后续转固',can_continue='付款有据',evidence_request='验收单',scope='PERIOD')
    assert validate(tmp_path,m,d,{})['passed']
    f['blocks_confirmation']='false'
    assert not validate(tmp_path,m,d,{})['passed']
    # A one-sided association still blocks; no shortcut through empty affected_vouchers.
    f['blocks_confirmation']=True;f['affected_vouchers']=[]
    assert not validate(tmp_path,m,d,{})['passed']
