"""Disposable source-first UI evidence; never opens retained data."""
import argparse
import base64
from pathlib import Path
from invoice_review_fixture_server import build, Scope, ArtifactInput, xlsx_fixture, INVOICE_HEADERS


def source_app(root):
    app = build(root)
    service = app.state.service
    scope = Scope(tenant_id='issue-plan-test', organization_id='fixture', legal_entity_id='方案核对甲',
                  ledger_id='test-ledger', accounting_period_id='2026-01', baseline_id='baseline-2026-01')
    rows = [INVOICE_HEADERS + ['发票状态']]
    rows += [[f'STATUS-{i}', '2026-01-25', '100', '13', '13%', '测试购买方', '已红冲-全额'] for i in range(1, 8)]
    content = xlsx_fixture([('发票基础信息', rows)])
    artifact = service.create_artifact(ArtifactInput(scope=scope, filename='销项状态核对.xlsx',
        observed_period='2026-01', source_purpose='business', content_base64=base64.b64encode(content).decode()), actor_id='fixture')
    service.parse_artifact(scope, artifact_id=artifact['object_id'], expected_version=artifact['version'],
                           actor_id='fixture', payload={'document_kind': 'sales_invoices'})
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(source_app(args.root), host='127.0.0.1', port=args.port)
