"""Disposable authenticated browser fixture. Never opens retained databases."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.auth import create_user, grant_scope
from app.config import Settings
from app.main import create_app
from app.ontology.contracts import Scope
from test_historical_preparation import workbooks


def build(root):
    if (root/'test.db').exists():
        raise RuntimeError('Refusing to reuse a database')
    app = create_app(Settings(root=Path(__file__).resolve().parents[1], database_path=root/'test.db', storage_path=root/'artifacts', require_auth=True))
    create_user(app.state.database,'history-tester','HistoricalTest!2026','accountant')
    create_user(app.state.database,'history-viewer','HistoricalTest!2026','viewer')
    scopes=[]
    for name in ['历史核对测试', '失败重试测试', '未授权企业']:
        scope=Scope(tenant_id='history-test',organization_id='fixture',legal_entity_id=name,ledger_id='test-ledger',accounting_period_id='2026-01',baseline_id='baseline-2026-01')
        app.state.service.create_scope(scope)
        if name!='未授权企业':
            for user in ['history-tester','history-viewer']:
                grant_scope(app.state.database,user,scope)
        scopes.append(scope.model_dump())
    balance,journal=workbooks()
    (root/'balance.xlsx').write_bytes(balance)
    (root/'journal.xlsx').write_bytes(journal)
    (root/'bad.xlsx').write_bytes(b'unsupported workbook fixture')
    (root/'fixture.json').write_text(json.dumps(scopes))
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--port',type=int,required=True)
    args=parser.parse_args()
    import uvicorn
    uvicorn.run(build(args.root),host='127.0.0.1',port=args.port)
