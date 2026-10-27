import base64
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import time

import openpyxl
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.ontology.contracts import Scope, ArtifactInput
from app.ontology.errors import PreconditionFailed, PermissionDenied
from app.autonomous_workflow import ORIGIN
from app.review_loop import REVIEW_POLICY_VERSION
from app.bookkeeping_profile import profile_reference

@pytest.fixture
def setup(tmp_path,scope):
    settings=Settings(root=Path(__file__).resolve().parents[1],database_path=tmp_path/'db.sqlite',storage_path=tmp_path/'sources',
        require_auth=False,autonomous_enabled=True,agent_send_full_records=True)
    app=create_app(settings);service=app.state.service;sc=Scope(**scope);service.create_scope(sc)
    book=openpyxl.Workbook();book.active.append(['日期','摘要','收入','支出']);book.active.append(['2026-03-01','股东投入',100,0]);data=BytesIO();book.save(data)
    source=service.create_artifact(ArtifactInput(scope=sc,filename='bank.xlsx',content_base64=base64.b64encode(data.getvalue()).decode()),actor_id='alice')
    w=service.autonomous
    def mature():
        j=w.current(sc);w._revise(sc,j,j['status'],{'queued_at':time.time()-6})
    def result(*args):
        sid=source['object_id'];ref={'source_id':sid,'sheet':'Sheet','row':2}
        delivery={'period':sc.accounting_period_id,'mode':'SOURCE_BOOKKEEPING','source_roles':{sid:'银行资料'},'bindings':{},'opening':[],
            'entries':[{'voucher':'候选001','date':'2026-03-01','code':c,'name':n,'memo':'投入','debit':d,'credit':cr,'source':ref}
                       for c,n,d,cr in [('1002','银行存款','100.00','0.00'),('4001','实收资本','0.00','100.00')]],
            'findings':[],'voucher_assessments':[{'voucher':'候选001','status':'READY_FOR_REVIEW','reason':'来源支持待人工复核','evidence':[ref],'finding_ids':[]}],
            'report':'原件制证模式的范围、处理方法与限制。'*10,'bank':[],'invoices':[], 'settlement_matches':[], 'employee_reimbursements':[], 'unassigned_reimbursement_invoices':[]}
        profile = profile_reference(w.bookkeeping_profile(sc))
        delivery['bookkeeping_profile'] = profile
        for assessment in delivery['voucher_assessments']:
            assessment['bookkeeping_profile'] = profile
        return {'review_policy_version':REVIEW_POLICY_VERSION,'delivery':delivery,'mechanical':{'passed':True,'checks':['来源']},'review':{'verdict':'pass','defects':[],
            'reviewed_bookkeeping_profile':profile, 'reviewed_employee_reimbursements':[],
            'coverage':[{'area':'投入','evidence':[ref],'conclusion':'符合原件'}],'ready_vouchers':['候选001'],
            'reviewed_settlement_matches':[], 'reviewed_decisions':[], 'reviewed_revisions':[], 'reviewed_responses':[]}}
    w.runner=result
    return app,service,sc,source,mature,result

def test_the_autonomous_path_shows_the_same_six_business_steps(setup):
    """两条处理路径共用 app/main_flow.py 的定义，不各写一份。

    分叉过一次：service.py 把同一组 id 叫「资料分析／待确认与校验」，
    这里叫「自主分析／独立审查」，同一个 analysis 两个名字。
    自主处理还曾经整格丢掉「导入历史资料」—— 它的 overview 里
    historical_preparation 直接是 None，第 2 步在界面上根本不存在。
    """
    app,s,sc,src,mature,result=setup
    progress=s.workbench(sc)['progress']

    assert [i['name'] for i in progress['stages'] if i['main_line']]==[
        '创建企业','导入历史资料','导入当月资料','AI 处理','人工确认','凭证生成与复核']
    assert progress['total_count']==6
    assert progress['prerequisite']['status'] in {'VALID','WAITING','ACTION_REQUIRED'}, \
        '第 2 步要有真实状态可依据，不能缺这一项'


def test_findings_waiting_on_a_person_are_the_human_confirmation_step(setup):
    """第 5 步「人工确认」= findings 里 needs_user 的那些。

    不是内部的「独立审查」—— 那一步是第二个 agent 会话在重查原件，人无事可做，
    把它显示成「人工确认」会让人去找根本不存在的待办。
    """
    app,s,sc,src,mature,result=setup;w=s.autonomous
    mature();assert w.tick(sc)

    stages={i['id']:i for i in s.workbench(sc)['progress']['stages']}
    pending=[f for f in s.workbench(sc)['autonomous_workflow']['findings'] if f.get('needs_user')]

    if pending:
        assert stages['confirmation']['status']=='WAITING'
        assert f'{len(pending)} 项需要你补充说明' == stages['confirmation']['summary']
    else:
        assert stages['confirmation']['status']=='COMPLETED'
        assert stages['confirmation']['summary']=='没有需要你确认的事项'


def test_queue_idempotence_and_scope_projection(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    first=w.current(sc)
    assert w.enqueue(sc,'alice')['object_id']==first['object_id']
    mature();assert w.tick(sc)
    view=s.workbench(sc)
    assert view['autonomous_workflow']['ready_count']==1
    assert view['progress']['current_stage']=='voucher'
    assert view['counts']['facts']==2
    assert not s.store.list_objects('ProcessingGroup',sc)
    v=view['vouchers'][0]
    command={'scope':sc.model_dump(),'action':'validate_draft','target_id':v['object_id'],'target_version':1,'idempotency_key':'review-one','payload':{}}
    client=TestClient(app)
    assert client.post('/api/v1/commands',json=command,headers={'X-Role':'viewer'}).status_code==403
    response=client.post('/api/v1/commands',json=command)
    assert response.status_code==200,response.text
    assert s.workbench(sc)['autonomous_workflow']['confirmed_count']==1
    assert not s.store.list_objects('DeliveryPackage',sc)
    with pytest.raises(PreconditionFailed,match='尚未正式交付'):
        s.close_period(sc,actor_id='alice',expected_version=1)


def test_current_admission_requires_explicit_settlement_scope(setup):
    _, service, scope, _, mature, result = setup
    workflow = service.autonomous
    def missing_scope(*args):
        candidate = result()
        candidate['delivery'].pop('settlement_matches')
        return candidate
    workflow.runner = missing_scope
    mature()
    assert not workflow.tick(scope)
    assert workflow.current(scope)['status'] == 'BLOCKED'
    assert not service.store.list_objects('VoucherVersion', scope)
    def corrected(*args):
        candidate = result()
        candidate['delivery']['settlement_matches'] = []
        candidate['review']['reviewed_settlement_matches'] = []
        return candidate
    workflow.runner = corrected
    workflow.enqueue(scope, 'alice', retry=True)
    mature()
    assert workflow.tick(scope)
    assert service.store.list_objects('VoucherVersion', scope)[0]['status'] == 'DRAFT'

def test_admission_rejects_inconsistent_voucher_dates_even_if_reviewer_passes(setup):
    _, service, scope, _, mature, result = setup
    def conflicting(*args):
        candidate = result()
        candidate['delivery']['entries'][1]['date'] = '2026-03-02'
        return candidate
    service.autonomous.runner = conflicting
    mature()
    assert not service.autonomous.tick(scope)
    assert '日期必须一致' in service.autonomous.current(scope)['data']['message']
    assert not service.store.list_objects('VoucherVersion', scope)

def test_new_source_invalidates_old_draft_and_queues_revision(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous;mature();w.tick(sc)
    v=s.workbench(sc)['vouchers'][0];old=w.current(sc)
    s.create_artifact(ArtifactInput(scope=sc,filename='proof.txt',content_base64=base64.b64encode(b'new proof').decode()),actor_id='alice')
    assert w.current(sc)['data']['revision']==2
    assert not s.workbench(sc)['vouchers']
    with pytest.raises(PreconditionFailed,match='已变化'):
        s.validate_draft(sc,voucher_id=v['object_id'],actor_id='alice',expected_version=1)
    assert s.store.get_object(old['object_id'],sc)['status']=='ACCEPTED'

def test_cancel_rejects_late_result_and_retry_preserves_history(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    def cancelled(*args):
        w.cancel(sc,'alice','operator');return result()
    w.runner=cancelled;mature();assert not w.tick(sc)
    assert w.current(sc)['status']=='CANCELLED'
    assert not s.store.list_objects('VoucherVersion',sc)
    old=w.current(sc);new=w.enqueue(sc,'alice',retry=True)
    assert new['data']['parent_id']==old['object_id']
    w.runner=result;mature();assert w.tick(sc)


def test_timeout_automatically_resumes_saved_work_without_new_revision(setup):
    _,service,scope,_,mature,result=setup;workflow=service.autonomous
    folders=[]
    def interrupted(folder,manifest,paths,context,settings,heartbeat,progress):
        folders.append(folder)
        (folder/'executor/work').mkdir(parents=True)
        (folder/'executor/work/plan.md').write_text('already read')
        raise TimeoutError('provider stalled')
    workflow.runner=interrupted;mature()
    assert not workflow.tick(scope)
    current=workflow.current(scope)
    assert current['status']=='QUEUED' and '自动接续' in current['data']['message']
    assert not service.store.list_objects('VoucherVersion',scope)
    def resumed(folder,manifest,paths,context,settings,heartbeat,progress):
        assert settings.autonomous_resume_from==folders[0]
        return result()
    workflow.runner=resumed;mature();assert workflow.tick(scope)
    assert workflow.current(scope)['object_id']==current['object_id']


def test_retry_uses_same_input_checkpoint_but_never_changed_inputs(setup):
    _,service,scope,src,mature,_=setup;workflow=service.autonomous
    old=workflow.current(scope)
    folder=workflow.settings.database_path.parent/'autonomous-runs'/old['object_id']/'attempt'
    workflow._revise(scope,old,'BLOCKED',{'folder':str(folder)})
    new=workflow.enqueue(scope,'alice',retry=True)
    assert workflow.continuation_from(scope,new)==folder
    changed={**new,'data':{**new['data'],'fingerprint':'different'}}
    assert workflow.continuation_from(scope,changed) is None
    other_model={**new,'data':{**new['data'],'runtime':{**new['data']['runtime'],'model':'other'}}}
    assert workflow.continuation_from(scope,other_model) is None


def test_previous_completed_counts_remain_visible_but_cannot_be_confirmed(setup,monkeypatch):
    _,service,scope,_,mature,_=setup;workflow=service.autonomous
    mature();assert workflow.tick(scope)
    old=workflow.current(scope);voucher=service.workbench(scope)['vouchers'][0]
    service.create_artifact(ArtifactInput(scope=scope,filename='proof.txt',content_base64=base64.b64encode(b'new proof').decode()),actor_id='alice')
    earlier={**old,'data':{**old['data'],'revision':0}}
    listing=service.store.list_objects
    monkeypatch.setattr(service.store,'list_objects',lambda kind,sc: [earlier,*listing(kind,sc)] if kind=='AutonomousMonthlyRun' else listing(kind,sc))
    view=service.workbench(scope)
    assert view['autonomous_workflow']['previous_result']=={'run_id':old['object_id'],'revision':1,'candidate_count':1,'ready_count':1,'pending_count':0}
    assert not view['vouchers'] and not view['autonomous_workflow']['accepted']
    with pytest.raises(PreconditionFailed):
        service.validate_draft(scope,voucher_id=voucher['object_id'],actor_id='alice',expected_version=1)

def test_explicit_history_recheck_keeps_old_result_and_requires_current_pending_issue(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    w.runner=lambda *args:nonblocking_result(result)
    mature();assert w.tick(sc)
    old=w.current(sc)
    client=TestClient(app)
    body={'scope':sc.model_dump(),'retry':True,'recheck':True}
    assert client.post('/api/v1/autonomous/start',json=body,headers={'X-Role':'viewer'}).status_code==403
    assert client.post('/api/v1/autonomous/start',json={**body,'retry':False}).status_code==409
    assert client.post('/api/v1/autonomous/start',json={**body,'recheck':'true'}).status_code==422
    response=client.post('/api/v1/autonomous/start',json=body)
    assert response.status_code==200,response.text
    new=w.current(sc)
    assert new['object_id']!=old['object_id'] and new['data']['parent_id']==old['object_id']
    assert new['data']['recheck_reason']=='EXISTING_EVIDENCE'
    assert s.store.get_object(old['object_id'],sc)['status']=='ACCEPTED'
    assert client.post('/api/v1/autonomous/start',json=body).json()['run_id']==new['object_id']
    w.runner=result
    mature();assert w.tick(sc)
    assert w.current(sc)['data']['recheck_reason']=='EXISTING_EVIDENCE'
    with pytest.raises(PreconditionFailed):
        w.enqueue(sc,'alice',retry=True,recheck=True)

def test_lease_claim_exclusive_and_expired_recovery(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous;mature()
    a=w._claim(sc);assert a and w._claim(sc) is None
    w._revise(sc,a,a['status'],{'lease_until':0})
    assert w.tick(sc)
    assert w.current(sc)['data']['attempt']==2
    assert len(s.store.list_objects('VoucherVersion',sc))==1

def test_source_mutation_during_execution_never_admitted(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    def change(*args):
        s.archive_artifact(sc,artifact_id=src['object_id'],actor_id='alice',expected_version=1)
        return result()
    w.runner=change;mature();assert not w.tick(sc)
    assert not s.store.list_objects('VoucherVersion',sc)
    assert s.workbench(sc)['autonomous_workflow']['stale']

def test_failure_is_system_owned_not_human_question(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    def fail(*args): raise TimeoutError('模型超时')
    w.runner=fail;mature();assert not w.tick(sc)
    assert w.current(sc)['status']=='QUEUED'
    mature();assert not w.tick(sc)
    assert w.current(sc)['status']=='QUEUED'
    mature();assert not w.tick(sc)
    view=s.workbench(sc)
    assert view['autonomous_workflow']['status']=='BLOCKED'
    assert not view['autonomous_workflow']['findings']
    assert view['material_review']['next_step']['owner']=='SYSTEM'

def test_answer_creates_new_revision_without_direct_confirmation(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    def pending(*args):
        r=result();d=r['delivery'];ref=d['entries'][0]['source']
        d['findings']=[{'id':'why','title':'投入性质','detail':'已查看原件，还缺资金性质','evidence':[ref],'affected_vouchers':['候选001'],'needs_user':True,
                        'decision':unresolved_decision('这笔投入是否约定归还？', '原件没有偿还约定，暂不能提出负债或权益分类方案')}]
        d['voucher_assessments'][0].update(status='NEEDS_EVIDENCE',finding_ids=['why'])
        r['review'].update(ready_vouchers=[],reviewed_decisions=['why']);return r
    w.runner=pending;mature();assert w.tick(sc)
    old=w.current(sc)
    new=w.answer(sc,'alice','operator',old['object_id'],'why','股东投入，合同随后补充')
    assert new['data']['revision']==2
    assert len(s.store.list_objects('AutonomousAnswer',sc))==1
    assert not s.store.list_objects('VoucherVersion',sc)
    with pytest.raises(PreconditionFailed,match='版本已变化'):
        w.answer(sc,'alice','operator',old['object_id'],'why','再提交')

def test_scope_authorization_and_client_output_rejected(setup):
    app,s,sc,src,mature,result=setup;client=TestClient(app)
    body={'scope':sc.model_dump(),'delivery':{'passed':True}}
    assert client.post('/api/v1/autonomous/start',json=body).status_code==422
    assert client.post('/api/v1/autonomous/start',json={'scope':sc.model_dump()},headers={'X-Role':'viewer'}).status_code==403
    with pytest.raises(PermissionDenied):s.autonomous.enqueue(sc,'alice','reviewer')

def test_modified_or_corrupt_source_not_reviewable(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous;mature();w.tick(sc)
    v=s.workbench(sc)['vouchers'][0]
    (s.store.database.settings.storage_path/src['data']['storage_path']).write_bytes(b'changed')
    with pytest.raises(PreconditionFailed,match='原件内容变化'):
        s.validate_draft(sc,voucher_id=v['object_id'],actor_id='alice',expected_version=1)

def test_revoked_permission_before_claim_is_persisted(setup,monkeypatch):
    app,s,sc,src,mature,result=setup;w=s.autonomous;mature()
    def deny(*args):raise PermissionDenied('范围授权已失效')
    monkeypatch.setattr(w,'authorize',deny)
    assert not w.tick(sc)
    assert w.current(sc)['status']=='BLOCKED'
    assert '授权' in w.current(sc)['data']['message']

def test_cancel_between_progress_transactions_cannot_resurrect(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    def runner(folder,manifest,paths,context,settings,heartbeat,progress):
        # Simulate cancel precisely after progress heartbeat commits.
        original=w._revise
        fired=[False]
        def intercept(scope,job,status,updates):
            updated=original(scope,job,status,updates)
            if set(updates)=={'lease_until'} and not fired[0]:
                fired[0]=True;w.cancel(sc,'alice','operator')
            return updated
        w._revise=intercept
        try:progress('REVIEWING',1,'review')
        finally:w._revise=original
        return result()
    w.runner=runner;mature();assert not w.tick(sc)
    assert w.current(sc)['status']=='CANCELLED'
    assert not s.store.list_objects('VoucherVersion',sc)

def test_partial_system_problem_has_retry_path(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    def blocked(*args):
        r=result();r['delivery']['voucher_assessments'][0]['status']='SYSTEM_BLOCKED';r['review']['ready_vouchers']=[];return r
    w.runner=blocked;mature();assert w.tick(sc)
    view=s.workbench(sc)['autonomous_workflow'];assert view['can_retry'] and view['blocked_count']==1
    assert '仍待处理' in view['label']
    assert w.enqueue(sc,'alice',retry=True)['status']=='QUEUED'

def test_viewer_can_read_process_but_cannot_write(setup):
    app,s,sc,src,mature,result=setup;client=TestClient(app)
    reply=client.post('/api/v1/autonomous/process',headers={'X-Role':'viewer'},json={'scope':sc.model_dump(),'run_id':s.autonomous.current(sc)['object_id']})
    assert reply.status_code==200,reply.text

def test_closed_period_during_model_call_rejects_result(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    def closed(*args):
        p=s.store.get_object(s._period_object_id(sc),sc);s.store.revise_object(p['object_id'],p['version'],sc,p['data'],status='CLOSED')
        return result()
    w.runner=closed;mature();assert not w.tick(sc)
    assert not s.store.list_objects('VoucherVersion',sc)

def test_production_requires_real_process_read_isolation(setup):
    app,s,sc,src,mature,result=setup
    with pytest.raises(ValueError,match='进程读取隔离'):
        replace(s.store.database.settings,environment='production').validate_runtime()

def test_retry_after_revoked_grant_does_not_accept_old_authorization(setup,monkeypatch):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    def revoked(*args):
        def deny(*_):raise PermissionDenied('用户已停用')
        monkeypatch.setattr(w,'authorize',deny)
        return result()
    w.runner=revoked;mature();assert not w.tick(sc)
    assert w.current(sc)['status']=='BLOCKED'
    assert not s.store.list_objects('VoucherVersion',sc)

def test_old_revision_route_cannot_strand_autonomous_candidate(setup):
    app,s,sc,src,mature,result=setup;mature();s.autonomous.tick(sc)
    v=s.workbench(sc)['vouchers'][0]
    with pytest.raises(PreconditionFailed,match='补充业务依据'):
        s.revise_voucher(sc,voucher_id=v['object_id'],actor_id='alice',expected_version=1,lines=v['data']['lines'])
    assert s.store.get_object(v['object_id'],sc)['version']==1
    assert s.validate_draft(sc,voucher_id=v['object_id'],actor_id='alice',expected_version=1)['status']=='LOCALLY_CONFIRMED'

def test_empty_new_workbench_does_not_expose_legacy_queues(setup):
    app,s,sc,src,mature,result=setup
    other=sc.model_copy(update={'legal_entity_id':'new-empty'})
    s.create_scope(other)
    view=s.workbench(other)
    assert view['autonomous_workflow']['status']=='WAITING_INPUT'
    assert not view['autonomous_workflow']['job']
    assert view['autonomous_workflow']['source_count']==0


def test_pending_entries_visible_without_admitting_or_confirming_them(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    def pending(*args):
        r=result();d=r['delivery'];ref=d['entries'][0]['source']
        d['findings']=[{'id':'purpose','title':'用途待核实','detail':'缺业务用途','needs_user':True,
                        'evidence':[ref],'affected_vouchers':['候选001'],
                        'decision':unresolved_decision('该笔付款对应什么业务？', '原件未包含订单用途，不能决定费用或往来科目')}]
        d['voucher_assessments'][0].update(status='NEEDS_EVIDENCE',finding_ids=['purpose'])
        r['review'].update(ready_vouchers=[],reviewed_decisions=['purpose'])
        return r
    w.runner=pending;mature();assert w.tick(sc)
    view=s.workbench(sc);flow=view['autonomous_workflow']
    assert flow['entry_preview_count']==1 and flow['ready_count']==0
    assert flow['entry_previews'][0]['entries']==pending()['delivery']['entries']
    assert flow['entry_previews'][0]['findings'][0]['id']=='purpose'
    assert view['progress']['current_stage']=='voucher'
    # 独立审查不再单占主线一格，它和自主分析一起算「AI 处理」：两步都是机器做的，
    # 对使用的人是同一件事。审查确实做完了这一点仍然要能看出来，所以查 summary。
    analysis=next(x for x in view['progress']['stages'] if x['id']=='analysis')
    assert analysis['status']=='COMPLETED' and '独立审查完成' in analysis['summary']
    assert not view['vouchers'] and not s.store.list_objects('VoucherVersion',sc)
    # Even a forged candidate cannot pass server-side confirmation.
    data={'origin':ORIGIN,'run_id':w.current(sc)['object_id'],'voucher_number':'候选001','lines':[]}
    forged=s.store.create_initial_object('VoucherVersion',sc,data,status='DRAFT')
    with pytest.raises(PreconditionFailed):
        s.validate_draft(sc,voucher_id=forged['object_id'],actor_id='alice',expected_version=1)
    old=w.current(sc)
    w.answer(sc,'alice','operator',old['object_id'],'purpose','补充一份订单，核实所有相关分录')
    assert not s.workbench(sc)['autonomous_workflow']['entry_previews']


def unresolved_decision(question, reason):
    return {'question':question, 'options':[], 'unavailable_reason':reason}


def nonblocking_result(result):
    r=result();d=r['delivery'];ref=d['entries'][0]['source']
    d['findings']=[{'id':'later','title':'后续履约待补','detail':'付款回单已证明支付，未来验收影响后续转固',
      'needs_user':True,'blocks_confirmation':False,'confirmation_reason':'仅确认付款往来；未提出费用或转固分录',
      'affected_vouchers':['候选001'],'evidence':[ref],
      'request':{'question':'设备何时验收？','why_needed':'决定后续转固时点','can_continue':'先确认付款往来',
                 'evidence_request':'后续验收记录','scope':'PERIOD'},
      'decision':unresolved_decision('设备何时验收？', '尚未提供验收事实，当前仅确认有据付款往来；实际验收后再确定转固时点')}]
    # Change to a payment-supported receivable in the fixture; never infer equity from a transfer alone.
    d['entries'][1].update(code='2241',name='其他应付款')
    d['voucher_assessments'][0]['finding_ids']=['later']
    r['review']['nonblocking_findings']=['later']
    r['review']['reviewed_decisions']=['later']
    return r


def test_nonblocking_request_retained_and_independently_approved(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    w.runner=lambda *args:nonblocking_result(result);mature();assert w.tick(sc)
    view=s.workbench(sc);flow=view['autonomous_workflow']
    assert flow['ready_count']==1 and flow['blocking_finding_count']==0
    assert flow['findings'][0]['needs_user'] and not flow['can_reassess']
    v=view['vouchers'][0]
    assert s.validate_draft(sc,voucher_id=v['object_id'],actor_id='alice',expected_version=1)['status']=='LOCALLY_CONFIRMED'
    assert s.workbench(sc)['autonomous_workflow']['findings'][0]['needs_user']


def test_nonblocking_without_reviewer_agreement_rejected(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    def unreviewed(*args):
        r=nonblocking_result(result);r['review'].pop('nonblocking_findings');return r
    w.runner=unreviewed;mature();assert not w.tick(sc)
    assert not s.store.list_objects('VoucherVersion',sc)
    assert '逐项确认' in w.current(sc)['data']['message']


def test_blocking_candidate_rejected_even_when_runner_claims_pass(setup):
    app,s,sc,src,mature,result=setup;w=s.autonomous
    def misleading(*args):
        r=nonblocking_result(result);r['delivery']['findings'][0]['blocks_confirmation']=True
        r['review']['nonblocking_findings']=[];return r
    w.runner=misleading;mature();assert not w.tick(sc)
    assert not s.store.list_objects('VoucherVersion',sc)


def test_old_policy_can_reassess_without_reupload_and_retains_history(setup,monkeypatch):
    from app import autonomous_workflow
    app,s,sc,src,mature,result=setup;w=s.autonomous
    monkeypatch.setattr(autonomous_workflow,'REVIEW_POLICY_VERSION',5)
    w.enqueue(sc,'alice')
    w.runner=lambda *args:{**result(),'review_policy_version':5}
    mature();assert w.tick(sc)
    previous=w.current(sc)
    monkeypatch.setattr(autonomous_workflow,'REVIEW_POLICY_VERSION',REVIEW_POLICY_VERSION)
    flow=s.workbench(sc)['autonomous_workflow']
    assert flow['stale'] and flow['can_retry'] and not flow['accepted']
    new=w.enqueue(sc,'alice',retry=True)
    assert new['data']['parent_id']==previous['object_id'] and new['data']['source_ids']==previous['data']['source_ids']
    assert s.store.get_object(previous['object_id'],sc)['status']=='ACCEPTED'
    assert not s.workbench(sc)['autonomous_workflow']['entry_previews']


def test_one_answer_reprocesses_all_related_vouchers_without_auto_confirmation(setup):
    from copy import deepcopy
    app,s,sc,src,mature,result=setup;w=s.autonomous;seen=[]
    def run(folder,manifest,paths,context,*args):
        seen.append(context)
        r=result();d=r['delivery'];ref=d['entries'][0]['source']
        d['entries'] += [{**e,'voucher':'候选002'} for e in list(d['entries'])]
        d['voucher_assessments'].append({**deepcopy(d['voucher_assessments'][0]),'voucher':'候选002'})
        if not context['statements']:
            d['findings']=[{'id':'shared','title':'共同用途','detail':'同一合同影响两张分录','needs_user':True,
                           'evidence':[ref],'affected_vouchers':['候选001','候选002'],
                           'decision':unresolved_decision('两笔付款对应哪个合同或项目？', '合同关系待补充，目前只能展示银行付款分录，不能认定业务归属')}]
            for a in d['voucher_assessments']:a.update(status='NEEDS_EVIDENCE',finding_ids=['shared'])
            r['review'].update(ready_vouchers=[],reviewed_decisions=['shared'])
        else:
            r['review']['ready_vouchers']=['候选001','候选002']
            d['decision_responses']=[{'answer_id':a['answer_id'],'outcome':'APPLIED',
                'explanation':'已按共同项目说明重新核对两笔付款，原件金额与分录均一致，仍交人工复核',
                'affected_vouchers':['候选001','候选002']} for a in context['statements']]
            r['review']['reviewed_responses']=[a['answer_id'] for a in context['statements']]
        return r
    w.runner=run;mature();assert w.tick(sc)
    old=w.current(sc);w.answer(sc,'alice','operator',old['object_id'],'shared','同一项目，两笔付款，共同查证')
    assert not s.workbench(sc)['vouchers']
    mature();assert w.tick(sc)
    view=s.workbench(sc)
    assert view['autonomous_workflow']['ready_count']==2 and view['autonomous_workflow']['confirmed_count']==0
    assert len(seen[-1]['statements'])==1 and seen[-1]['statements'][0]['evidence_kind']=='USER_STATEMENT'
    assert seen[-1]['prior_findings'][0]['affected_vouchers']==['候选001','候选002']
    assert len(s.store.list_objects('AutonomousAnswer',sc))==1
