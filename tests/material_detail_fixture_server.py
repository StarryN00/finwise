"""Disposable navigation fixtures, including repeated issues on three originals."""
import argparse
import base64
from pathlib import Path

from materials_fixture_server import material_app, Scope, ArtifactInput, xlsx_fixture, INVOICE_HEADERS


def build(root):
    app = material_app(root)
    service = app.state.service
    scope = Scope(tenant_id='issue-plan-test', organization_id='fixture', legal_entity_id='方案核对甲',
                  ledger_id='test-ledger', accounting_period_id='2026-01', baseline_id='baseline-2026-01')
    for index in [2, 3]:
        content = xlsx_fixture([('发票', [INVOICE_HEADERS, [f'I-GAP-{index}', '2026-01-03', '100', '13', 'invalid', '测试对方']])])
        artifact = service.create_artifact(ArtifactInput(scope=scope, filename=f'1月发票补充{index}.xlsx',
            observed_period='2026-01', source_purpose='business', content_base64=base64.b64encode(content).decode()), actor_id='fixture')
        service.parse_artifact(scope, artifact_id=artifact['object_id'], expected_version=artifact['version'],
                               actor_id='fixture', payload={'document_kind': 'purchase_invoices'})
    content = xlsx_fixture([('账户明细', [
        ['账号:001-234567890', '户名:合成企业', '币种:人民币'],
        ['交易时间', '收入金额', '支出金额', '账户余额', '对方账号', '对方户名'],
        ['2026-01-08', '100', '0', '100', '999999999', '对手公司'],
        ['2026-02-02', '0', '10', '90', '888888888', '对手公司']])])
    artifact = service.create_artifact(ArtifactInput(scope=scope, filename='农业银行测试流水.xlsx', observed_period='2026-01',
        source_purpose='business', content_base64=base64.b64encode(content).decode()), actor_id='fixture')
    service.parse_artifact(scope, artifact_id=artifact['object_id'], expected_version=artifact['version'],
                          actor_id='fixture', payload={'document_kind': 'bank_statement'})
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(build(args.root), host='127.0.0.1', port=args.port)
