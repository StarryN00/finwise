"""Disposable real HTTP/UI fixture with a deterministic analyst, no real company data."""
import argparse
from pathlib import Path
import sys
import uvicorn
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from test_autonomous_workflow import setup
from test_stage4_loop import decision_result

def build(root):
    root.mkdir(parents=True,exist_ok=True)
    scope=dict(tenant_id='loop-test',organization_id='loop-test',legal_entity_id='循环复核测试企业',ledger_id='主账套',accounting_period_id='2026-03',baseline_id='loop-march')
    app,s,sc,src,mature,base=setup.__wrapped__(root,scope)
    w=s.autonomous;w.runner=lambda *args:decision_result(base,w.review_context(sc))
    mature();assert w.tick(sc)
    for worker in [s.historical,s.payroll_mapping,s.problem_review,s.material_agent,app.state.monthly_agent]:worker.start=lambda:None
    return app
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--port',type=int,default=8778);a=p.parse_args()
    uvicorn.run(build(a.root),host='127.0.0.1',port=a.port)
