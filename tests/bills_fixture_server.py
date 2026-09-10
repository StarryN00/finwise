"""Synthetic bill fixtures; never connect to retained financial data."""
import argparse
import base64
from pathlib import Path
from materials_fixture_server import material_app, Scope, ArtifactInput, xlsx_fixture


def build(root):
    app = material_app(root)
    s = app.state.service
    scope = Scope(tenant_id='issue-plan-test', organization_id='fixture', legal_entity_id='方案核对甲',
                  ledger_id='test-ledger', accounting_period_id='2026-01', baseline_id='baseline-2026-01')
    content = xlsx_fixture([('票据', [
        ['票据（包）号', '子票区间', '出票日', '到期日', '票据（包）金额', '票据状态'],
        ['TEST-PACK', '1,2', '20251101', '20260501', '20265', '已收票'],
        ['TEST-PACK', '3,4', '20251101', '20260501', '15000', '已收票'],
        ['TEST-PACK', '5,6', '20251101', '20260501', '3000', '已收票']])])
    a = s.create_artifact(ArtifactInput(scope=scope, filename='1月票据测试.xlsx', observed_period='2026-01',
        source_purpose='business', content_base64=base64.b64encode(content).decode()), actor_id='fixture')
    s.parse_artifact(scope, artifact_id=a['object_id'], expected_version=a['version'], actor_id='fixture',
                    payload={'document_kind': 'electronic_acceptance'})
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(build(args.root), host='127.0.0.1', port=args.port)
