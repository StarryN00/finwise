"""Synthetic bank account UX fixture. No retained data or model calls."""
import argparse,base64,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from historical_plans_fixture_server import build
from app.ontology.contracts import Scope,ArtifactInput
from test_bank_accounts import bank_file

def app_for(root):
    app=build(root);s=app.state.service
    scope=Scope(tenant_id='issue-plan-test',organization_id='fixture',legal_entity_id='方案核对甲',ledger_id='test-ledger',accounting_period_id='2026-01',baseline_id='baseline-2026-01')
    content=bank_file()
    # January fixtures use their actual source month; one April exception remains.
    from test_tabular_ingestion import xlsx_fixture
    content=xlsx_fixture([('账户明细',[
        ['账号:001-234567890','户名:合成企业','币种:人民币'],
        ['交易时间','收入金额','支出金额','账户余额','对方账号','对方户名'],
        ['2026-01-08','100','0','100','999999999','对手公司'],
        ['2026-02-02','0','10','90','888888888','对手公司']])])
    a=s.create_artifact(ArtifactInput(scope=scope,filename='农业银行测试流水.xlsx',observed_period='2026-01',content_base64=base64.b64encode(content).decode()),actor_id='fixture')
    s.parse_artifact(scope,artifact_id=a['object_id'],expected_version=a['version'],actor_id='fixture',payload={'document_kind':'bank_statement'})
    return app

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--port',type=int,required=True);a=p.parse_args()
    import uvicorn
    uvicorn.run(app_for(a.root),host='127.0.0.1',port=a.port)
