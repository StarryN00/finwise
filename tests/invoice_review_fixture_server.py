"""Synthetic non-positive invoices, never connected to real Staging."""
import argparse, base64, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from materials_fixture_server import material_app
from app.ontology.contracts import Scope, ArtifactInput
from test_tabular_ingestion import xlsx_fixture, INVOICE_HEADERS


def build(root):
    app=material_app(root);s=app.state.service
    scope=Scope(tenant_id='issue-plan-test',organization_id='fixture',legal_entity_id='方案核对甲',ledger_id='test-ledger',accounting_period_id='2026-01',baseline_id='baseline-2026-01')
    content=xlsx_fixture([('发票',[INVOICE_HEADERS+['发票状态','备注'],
        ['RED-1','2026-01-02','-100','-13','13%','测试对方'],
        ['ZERO-1','2026-01-03','0','0','13%','测试对方'],
        ['RED-OLD','2025-12-02','-100','-13','13%','测试对方'],
        ['26322000000625714621','2026-01-25','-100','-13','13%','测试对方','正常',
         '被红冲蓝字数电发票号码：26322000000633306346 红字发票信息确认单编号：32058326011138350731']])])
    a=s.create_artifact(ArtifactInput(scope=scope,filename='1月红字及零金额发票.xlsx',observed_period='2026-01',source_purpose='business',content_base64=base64.b64encode(content).decode()),actor_id='fixture')
    s.parse_artifact(scope,artifact_id=a['object_id'],expected_version=a['version'],actor_id='fixture',payload={'document_kind':'sales_invoices'})
    return app


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--port',type=int,required=True);args=p.parse_args()
    import uvicorn
    uvicorn.run(build(args.root),host='127.0.0.1',port=args.port)
