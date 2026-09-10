"""Isolated UI fixture, never connects to a real provider or retained database."""
import argparse,base64,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from historical_plans_fixture_server import build
from app.ontology.contracts import Scope,ArtifactInput
from app.ontology.gateway import GatewayResult
from test_payroll_mapping import content,proposal

def app_for(root):
    app=build(root);s=app.state.service
    def fake(scope,**kwargs):
        p=proposal();p['sheets'][0]['fields']['housing_fund']='F'
        return GatewayResult(p,'fixture','fixture-mapping',True,'fixture','i','o',20,{})
    s.gateway.complete=fake
    scope=Scope(tenant_id='issue-plan-test',organization_id='fixture',legal_entity_id='方案核对甲',ledger_id='test-ledger',accounting_period_id='2026-01',baseline_id='baseline-2026-01')
    a=s.create_artifact(ArtifactInput(scope=scope,filename='自定义工资表.xlsx',observed_period='2026-01',content_base64=base64.b64encode(content('2026-01')).decode()),actor_id='plan-author')
    s.parse_artifact(scope,artifact_id=a['object_id'],expected_version=a['version'],actor_id='plan-author',payload={'document_kind':'payroll'})
    other=scope.model_copy(update={'legal_entity_id':'方案核对乙'})
    a=s.create_artifact(ArtifactInput(scope=other,filename='乙企业工资表.xlsx',observed_period='2026-01',content_base64=base64.b64encode(content('2026-01')).decode()),actor_id='plan-author')
    a=s.parse_artifact(other,artifact_id=a['object_id'],expected_version=a['version'],actor_id='plan-author',payload={'document_kind':'payroll'})['artifact']
    j=s.execute_command(other,action='request_payroll_mapping',target_id=a['object_id'],target_version=a['version'],idempotency_key='fixture-failed-mapping',actor_id='plan-author',role='accountant')['effect']['object']
    s.store.revise_object(j['object_id'],j['version'],other,{**j['data'],'error':'测试识别超时，请显式重试'},status='FAILED',created_by='fixture')
    return app

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--port',type=int,required=True);args=p.parse_args()
    import uvicorn
    uvicorn.run(app_for(args.root),host='127.0.0.1',port=args.port)
