"""Disposable material-review browser fixtures."""
import argparse,base64,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from historical_plans_fixture_server import build
from app.ontology.contracts import Scope,ArtifactInput
from test_tabular_ingestion import xlsx_fixture,INVOICE_HEADERS


def material_app(root):
    app=build(root);s=app.state.service
    for name in ['方案核对甲']:
        scope=Scope(tenant_id='issue-plan-test',organization_id='fixture',legal_entity_id=name,ledger_id='test-ledger',accounting_period_id='2026-01',baseline_id='baseline-2026-01')
        job=s.workbench(scope)['historical_preparation']
        for issue in job['data']['result']['issues']:
            s.historical_plans.save(scope,job['object_id'],job['version'],'plan-author',{'issue_key':issue['issue_key'],'route':'unavailable','conclusion':'暂无其他历史材料','expected_plan_version':0})
        rows=[INVOICE_HEADERS]+[[f'I-{i}','2026-01-02','100','13','13%','测试对方'] for i in range(7)]+[['I-GAP','2026-01-03','100','13','invalid','测试对方'],['I-OLD','2025-12-03','100','13','13%','测试对方']]
        content=xlsx_fixture([('发票',rows)])
        a=s.create_artifact(ArtifactInput(scope=scope,filename='1月发票.xlsx',observed_period='2026-01',source_purpose='business',content_base64=base64.b64encode(content).decode()),actor_id='fixture')
        s.parse_artifact(scope,artifact_id=a['object_id'],actor_id='fixture',expected_version=a['version'],payload={'document_kind':'purchase_invoices'})
        (root/'supplement.xlsx').write_bytes(xlsx_fixture([('发票',[INVOICE_HEADERS,['I-SUP','2026-01-04','100','13','13%','测试对方']])]))
    return app


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--port',type=int,required=True);args=p.parse_args()
    import uvicorn
    uvicorn.run(material_app(args.root),host='127.0.0.1',port=args.port)
