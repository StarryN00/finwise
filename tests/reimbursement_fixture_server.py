"""Disposable browser fixture: real-model output replay, simulated response handling only."""
from pathlib import Path
from copy import deepcopy
import argparse,base64,json,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.main import create_app
from app.ontology.contracts import Scope,ArtifactInput
from app.bookkeeping_profile import profile_reference
from app.autonomous_checks import validate
from app.autonomous_runtime import prepare

def build(root,result_root):
 root.mkdir(parents=True,exist_ok=True)
 app=create_app(Settings(root=ROOT,database_path=root/'test.db',storage_path=root/'sources',require_auth=False,autonomous_enabled=True,agent_send_full_records=True))
 service=app.state.service;w=service.autonomous
 scope=Scope(tenant_id='reimbursement-fixture',organization_id='reimbursement-fixture',legal_entity_id='个人报销浏览器验收企业',ledger_id='隔离测试账套',accounting_period_id='2026-08',baseline_id='test')
 service.create_scope(scope)
 src=service.create_artifact(ArtifactInput(scope=scope,filename='匿名报销样本.xlsx',content_base64=base64.b64encode((result_root/'anonymous.xlsx').read_bytes()).decode()),actor_id='test-operator')
 policy,_=w.save_travel_policy(scope,'test-operator','operator',enabled=True,expected_version=0,source_note='隔离浏览器测试规则，不写实际企业')
 result=json.loads((result_root/'result.json').read_text())
 def rewrite(value):
  if isinstance(value,dict):return {k:(src['object_id'] if k=='source_id' and v=='anonymous' else rewrite(v)) for k,v in value.items()}
  if isinstance(value,list):return [rewrite(v) for v in value]
  return value
 result=rewrite(result)
 result['delivery']['source_roles']={src['object_id']:'匿名隔离报销测试原件'}
 for a in result['delivery']['travel_policy_applications']:a['policy_id']=policy['id']
 result['review']['reviewed_travel_policy']={k:policy[k] for k in ['id','version']}
 def analyst(folder,manifest,paths,context,settings,heartbeat,progress):
  r=deepcopy(result);d=r['delivery'];profile=profile_reference(context['bookkeeping_profile'])
  d['bookkeeping_profile']=profile
  for a in d['voucher_assessments']:a['bookkeeping_profile']=profile
  d['decision_responses']=[dict(answer_id=a['answer_id'],outcome='UNRESOLVED',explanation='浏览器隔离桩仅验证说明提交及版本接续；不模拟真实模型的归属判断。',affected_vouchers=[]) for a in context['statements']]
  r['review']['reviewed_responses']=[a['answer_id'] for a in context['statements']]
  r['review']['reviewed_bookkeeping_profile']=profile
  workspace,_=prepare(folder,manifest,paths,context,settings)
  checked=validate(workspace,manifest,d,{},context);assert checked['passed'],checked['errors']
  r['mechanical']=checked
  return r
 w.runner=analyst
 j=w.current(scope);w._revise(scope,j,j['status'],{'queued_at':time.time()-6});assert w.tick(scope),w.current(scope)['data']['message']
 for worker in [service.historical,service.payroll_mapping,service.problem_review,service.material_agent,app.state.monthly_agent]:worker.start=lambda:None
 return app

if __name__=='__main__':
 import uvicorn
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--result-root',type=Path,required=True);p.add_argument('--port',type=int,default=8793);args=p.parse_args()
 uvicorn.run(build(args.root.resolve(),args.result_root.resolve()),host='127.0.0.1',port=args.port)
