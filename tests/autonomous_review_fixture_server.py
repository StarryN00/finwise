"""Disposable review-flow browser fixture; never opens a real company database."""
import argparse
from copy import deepcopy
from pathlib import Path
import sys
import uvicorn

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from test_autonomous_workflow import setup, nonblocking_result


def build(root):
    root.mkdir(parents=True,exist_ok=True)
    scope=dict(tenant_id='review-test',organization_id='review-test',legal_entity_id='复核流程测试企业',
               ledger_id='主账套',accounting_period_id='2026-03',baseline_id='review-test-march')
    app,s,sc,src,mature,result=setup.__wrapped__(root,scope)
    r=nonblocking_result(result);d=r['delivery']
    d['entries'] += [{**e,'voucher':'候选002'} for e in list(d['entries'])]
    d['findings'].append({'id':'purpose','title':'设备用途待核实','detail':'已核对金额100.00；请补安装用途。',
       'needs_user':True,'blocks_confirmation':True,'affected_vouchers':['候选002'],'evidence':[d['entries'][0]['source']],
       'request':{'question':'安装的是自用设备还是客户订单设备？','why_needed':'决定资产或订单成本归属',
                  'can_continue':'银行付款100.00及对方已核对','evidence_request':'注明安装对象的验收记录','scope':'PERIOD'}})
    d['voucher_assessments'].append({**deepcopy(d['voucher_assessments'][0]),'voucher':'候选002',
       'status':'NEEDS_EVIDENCE','finding_ids':['purpose'],'reason':'金额有据，用途待查，不可确认'})
    r['review_policy_version']=1 # Exercise explicit policy re-review of an older accepted run.
    s.autonomous.runner=lambda *args:r
    mature();assert s.autonomous.tick(sc)
    for worker in [s.autonomous,s.historical,s.payroll_mapping,s.problem_review,s.material_agent,app.state.monthly_agent]:
        worker.start=lambda:None
    return app


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--port',type=int,default=8778)
    a=p.parse_args();uvicorn.run(build(a.root),host='127.0.0.1',port=a.port)
