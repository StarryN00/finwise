"""Decision-loop state, evidence gates and standalone-tool integration."""
from copy import deepcopy
from pathlib import Path
import base64
import json
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest
from test_autonomous_workflow import setup, nonblocking_result
from app.autonomous_runtime import prepare
from app.autonomous_checks import validate
from app.review_loop import REVIEW_POLICY_VERSION, review_loop_errors, review_loop_approved
from app.ontology.contracts import ArtifactInput
from app.ontology.errors import PreconditionFailed


def decision_result(base, context):
    r=base();r['review_policy_version']=REVIEW_POLICY_VERSION;d=r['delivery'];ref=d['entries'][0]['source']
    statements=context.get('statements',[])
    choices=[a for a in statements if a.get('kind')=='REVIEW_SELECTION']
    applied=choices and choices[-1]['option']['id']=='loan'
    d['findings']=[{'id':'nature','title':'这笔股东转入款需要归还吗？','detail':'到账100.00已核对，银行摘要未说明是否偿还。',
        'needs_user':not applied,'blocks_confirmation':True,'affected_vouchers':['候选001'],'evidence':[ref],
        'request':dict(question='股东转入款是否需要偿还？',why_needed='决定负债或权益归属',can_continue='已核对银行到账100.00',evidence_request='可先说明约定是否偿还',scope='PERIOD')}]
    if not applied:
        d['findings'][0]['decision']={'question':'按实际约定，这笔转入款属于哪种情况？','options':[
          dict(id='loan',label='需要归还，是股东借款',kind='BUSINESS_FACT',recommended=False,basis='银行已记录股东转入100.00，性质仍待陈述',assumptions=['实际约定需要归还，属于企业收到的借款'],effect='拟将100.00从实收资本转为其他应付款；不改变银行到账金额',next_step='核实陈述与原件是否冲突，重算负债和权益后交复核'),
          dict(id='unknown',label='暂时无法判断',kind='DEFER',recommended=False,basis='现有摘要不能区分借款与出资',assumptions=['目前不清楚是否需要归还'],effect='保留到账记录和原分录预览，性质继续待定，不能确认此张凭证',next_step='记录当前边界，不推测为借款或出资')],'unavailable_reason':''}
    d['voucher_assessments'][0].update(status='READY_FOR_REVIEW' if applied else 'NEEDS_EVIDENCE',finding_ids=['nature'],reason='用户已陈述为需归还款，原件到账与陈述一致' if applied else '到账有据，负债或权益性质尚待判断')
    if applied:
        entries=deepcopy(d['entries']);entries[1].update(code='2241',name='其他应付款',memo='股东借款')
        d['revisions']=[dict(voucher='候选001',reason='根据用户明确的偿还约定修订权益为负债，未改变原账',answer_ids=[choices[-1]['answer_id']],entries=entries)]
    d['decision_responses']=[dict(answer_id=a['answer_id'],outcome='APPLIED' if applied or a['kind']=='MATERIALS_COMPLETE' else 'UNRESOLVED',explanation='已按现有资料提出可行方案；未把资料范围声明当成业务证据' if a['kind']=='MATERIALS_COMPLETE' else '已按陈述修订负债科目，等待凭证复核' if applied else '目前无法判断偿还约定，保留凭证待核实',affected_vouchers=['候选001']) for a in statements]
    r['review'].update(ready_vouchers=['候选001'] if applied else [],reviewed_decisions=[] if applied else ['nature'],reviewed_revisions=['候选001'] if applied else [],reviewed_responses=[a['answer_id'] for a in statements])
    return r


def test_materials_selection_recompute_review_and_original_preservation(setup):
    app,s,sc,src,mature,base=setup;w=s.autonomous
    w.runner=lambda *args:decision_result(base,w.review_context(sc))
    mature();assert w.tick(sc);client=TestClient(app)
    body={'scope':sc.model_dump(),'run_id':w.current(sc)['object_id']}
    assert client.post('/api/v1/autonomous/materials-complete',json=body,headers={'X-Role':'viewer'}).status_code==403
    assert client.post('/api/v1/autonomous/materials-complete',json=body).status_code==200
    assert w.review_context(sc)['materials_complete']
    assert not s.workbench(sc)['vouchers']
    assert client.post('/api/v1/autonomous/materials-complete',json=body).status_code==409
    mature();assert w.tick(sc)
    body.update(run_id=w.current(sc)['object_id'],finding_id='nature',option_id='loan',acknowledged=True)
    assert client.post('/api/v1/autonomous/decision',json={**body,'acknowledged':'true'}).status_code==422
    assert client.post('/api/v1/autonomous/decision',json={**body,'acknowledged':False}).status_code==409
    assert client.post('/api/v1/autonomous/decision',json={**body,'option_id':'forged'}).status_code==409
    assert client.post('/api/v1/autonomous/decision',json={**body,'option':{'label':'overwrite'}}).status_code==422
    assert client.post('/api/v1/autonomous/decision',json=body).status_code==200
    assert not s.workbench(sc)['vouchers']
    saved=w.review_context(sc)['statements'][-1]
    assert saved['option']['label']=='需要归还，是股东借款' and saved['evidence_kind']=='USER_STATEMENT'
    mature();assert w.tick(sc)
    view=s.workbench(sc);p=view['autonomous_workflow']['entry_previews'][0];v=view['vouchers'][0]
    assert p['original_entries'][1]['code']=='4001' and p['entries'][1]['code']=='2241'
    assert v['status']=='DRAFT' and not v['data']['formal_balance_impact']
    assert len(view['autonomous_workflow']['decision_responses'])==2
    s.validate_draft(sc,voucher_id=v['object_id'],actor_id='alice',expected_version=1)
    assert s.workbench(sc)['autonomous_workflow']['confirmed_count']==1
    s.create_artifact(ArtifactInput(scope=sc,filename='more.txt',content_base64=base64.b64encode(b'additional').decode()),actor_id='alice')
    assert not w.review_context(sc)['materials_complete']


def test_deferral_and_independent_review_cannot_be_bypassed(setup):
    app,s,sc,src,mature,base=setup;w=s.autonomous
    w.runner=lambda *args:decision_result(base,w.review_context(sc));mature();assert w.tick(sc)
    w.choose(sc,'alice','operator',w.current(sc)['object_id'],'nature','unknown',True)
    mature();assert w.tick(sc)
    assert not s.workbench(sc)['vouchers']
    assert w.current(sc)['data']['result']['delivery']['decision_responses'][0]['outcome']=='UNRESOLVED'
    r=decision_result(base,w.review_context(sc))
    r['delivery']['revisions']=[dict(voucher='候选001',reason='猜测',answer_ids=[w.review_context(sc)['statements'][0]['answer_id']],entries=r['delivery']['entries'])]
    assert any('暂无法判断' in e for e in review_loop_errors(r['delivery'],w.review_context(sc)))
    r['review']['reviewed_decisions']=[]
    assert not review_loop_approved(r['delivery'],r['review'])


def test_user_response_coverage_and_missing_decision_block_admission(setup):
    app,s,sc,src,mature,base=setup;w=s.autonomous
    r=decision_result(base,{'statements':[]});del r['delivery']['findings'][0]['decision']
    w.runner=lambda *args:r;mature();assert not w.tick(sc)
    assert w.current(sc)['status']=='BLOCKED' and not s.workbench(sc)['vouchers']
    r=decision_result(base,{'statements':[]})
    assert any('逐项说明' in e for e in review_loop_errors(r['delivery'],{'review_loop_version':3,'statements':[{'answer_id':'actual'}]}))


def test_identical_confirmed_voucher_carries_but_changed_assessment_requires_review(setup):
    app,s,sc,src,mature,base=setup;w=s.autonomous
    def unchanged(*args):
        r=nonblocking_result(base)
        statements=w.review_context(sc)['statements']
        r['delivery']['decision_responses']=[{'answer_id':a['answer_id'],'outcome':'APPLIED',
            'explanation':'资料范围声明已记录；有据付款分录不变，后续验收仍单独跟踪',
            'affected_vouchers':['候选001']} for a in statements]
        r['review']['reviewed_responses']=[a['answer_id'] for a in statements]
        return r
    w.runner=unchanged
    mature();assert w.tick(sc);v=s.workbench(sc)['vouchers'][0]
    s.validate_draft(sc,voucher_id=v['object_id'],actor_id='alice',expected_version=1)
    w.materials_complete(sc,'alice','operator',w.current(sc)['object_id']);mature();assert w.tick(sc)
    new=s.workbench(sc)['vouchers'][0]
    assert new['status']=='LOCALLY_CONFIRMED' and new['data']['carried_from']==v['object_id']
    w.enqueue(sc,'alice',retry=True,recheck=True)
    def changed(*args):
        r=unchanged();r['delivery']['voucher_assessments'][0]['reason']='新的业务判断';return r
    w.runner=changed;mature();assert w.tick(sc)
    assert s.workbench(sc)['vouchers'][0]['status']=='DRAFT'


def test_generated_checker_executes_decision_contract_and_revisions(setup,tmp_path):
    app,s,sc,src,mature,base=setup;w=s.autonomous
    from app.stage23_pilot import sha256,write_json
    source=w.settings.storage_path/src['data']['storage_path']
    manifest={'period':sc.accounting_period_id,'sources':[dict(id=src['object_id'],path='sources/bank.xlsx',sha256=sha256(source))]}
    context={'review_loop_version':3,'statements':[], 'bookkeeping_profile':w.bookkeeping_profile(sc)}
    workspace,_=prepare(tmp_path/'standalone',manifest,{src['object_id']:source},context,w.settings)
    r=decision_result(base,context);write_json(workspace/'work/delivery.json',r['delivery'])
    proc=subprocess.run([sys.executable,str(workspace/'tools/check.py')],capture_output=True,text=True)
    check=json.loads(proc.stdout)
    assert proc.returncode==0 and check['passed'],check
    context['statements']=[dict(answer_id='a1',kind='REVIEW_SELECTION',option={'id':'loan','kind':'BUSINESS_FACT'})]
    r=decision_result(base,context);d=r['delivery']
    assert validate(workspace,manifest,d,{},context)['passed']
    d['revisions'][0]['entries'][0]['debit']='101.00'
    assert not validate(workspace,manifest,d,{},context)['passed']
    d['revisions'][0]['entries'][0]['debit']='100.00';d['revisions'][0]['answer_ids']=['invented']
    assert not validate(workspace,manifest,d,{},context)['passed']
