"""Disposable real HTTP/UI flow; simulated analyst is explicitly not a real-model test."""
import argparse
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from test_autonomous_workflow import setup
from app.autonomous_checks import validate
from app.autonomous_runtime import prepare
from app.auth import create_user, grant_scope


def build(root):
    root.mkdir(parents=True,exist_ok=True)
    scope=dict(tenant_id='profile-test',organization_id='profile-test',legal_entity_id='记账方式验收企业',
               ledger_id='验收账套',accounting_period_id='2026-03',baseline_id='profile-march')
    app,service,sc,source,mature,result=setup.__wrapped__(root,scope)
    create_user(app.state.database,'profile-tester','profile-test-password','accountant')
    grant_scope(app.state.database,'profile-tester',sc)
    workflow=service.autonomous
    def analyst(folder,manifest,paths,context,settings,heartbeat,progress):
        r=result();d=r['delivery'];ref=d['entries'][0]['source']
        d['bank']=[dict(source=ref,date='2026-03-01',income='100.00',expense='0.00')]
        workspace,_=prepare(folder,manifest,paths,context,settings)
        checked=validate(workspace,manifest,d,{},context)
        assert checked['passed'],checked['errors']
        r['mechanical']=checked
        return r
    workflow.runner=analyst;mature();assert workflow.tick(sc),workflow.current(sc)['data']['message']
    for worker in [service.historical,service.payroll_mapping,service.problem_review,service.material_agent,app.state.monthly_agent]:
        worker.start=lambda:None
    return app


if __name__=='__main__':
    import uvicorn
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--port',type=int,default=8792);args=p.parse_args()
    uvicorn.run(build(args.root),host='127.0.0.1',port=args.port)
