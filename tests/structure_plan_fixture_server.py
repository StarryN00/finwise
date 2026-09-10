"""Disposable authenticated browser fixture. Its model is deliberately simulated."""
import argparse
import base64
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from historical_plans_fixture_server import build
from app.ontology.contracts import Scope, ArtifactInput
from app.ontology.gateway import GatewayResult
from test_tabular_ingestion import xlsx_fixture


def app_for(root):
    app=build(root); service=app.state.service
    proposal={'schema_version':'structure-plan-v1','outcome':'PLAN','sheets':[
        {'sheet_index':0,'role':'DATA','header_row':2,'fields':{
            'transaction_date':'A','income':'B','expense':'C','balance':'D'},'reference_rows':[]}]}
    def fake(scope,**kwargs):
        assert kwargs['stage']=='STRUCTURE_PLAN'
        return GatewayResult(proposal,'fixture','fixture-structure',True,'structure-plan-prompt-v1','i','o',20,{})
    service.gateway.complete=fake
    scope=Scope(tenant_id='issue-plan-test',organization_id='fixture',legal_entity_id='方案核对甲',ledger_id='test-ledger',accounting_period_id='2026-01',baseline_id='baseline-2026-01')
    content=xlsx_fixture([('流水',[['自定义银行流水 · 人民币元'],
        ['记账日期','入账收入','发生支出','结余金额'],
        ['2026-01-01',100,0,100],['2026-01-02',0,20,80]])])
    artifact=service.create_artifact(ArtifactInput(scope=scope,filename='结构验收银行流水.xlsx',
        observed_period='2026-01',content_base64=base64.b64encode(content).decode()),actor_id='plan-author')
    service.parse_artifact(scope,artifact_id=artifact['object_id'],expected_version=artifact['version'],
        actor_id='plan-author',payload={'document_kind':'bank_statement'})
    return app


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--port',type=int,required=True);args=p.parse_args()
    import uvicorn
    uvicorn.run(app_for(args.root),host='127.0.0.1',port=args.port)
