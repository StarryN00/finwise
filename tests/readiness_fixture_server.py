"""Disposable, authenticated browser fixtures; never opens the retained Staging DB."""
import argparse
import base64
import json
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.auth import create_user, grant_scope
from app.config import Settings
from app.main import create_app
from app.ontology.contracts import ArtifactInput, Scope
from test_tabular_ingestion import INVOICE_HEADERS, xlsx_fixture
from test_baseline_candidate import HEADERS


def build(root):
    app = create_app(Settings(root=ROOT, database_path=root/'test.db', storage_path=root/'artifacts', require_auth=True))
    service, db = app.state.service, app.state.store.database
    create_user(db, 'readiness-operator', 'ReadinessTest!2026', 'accountant')
    create_user(db, 'readiness-viewer', 'ReadinessTest!2026', 'viewer')
    scopes = []
    for company in ['校验测试企业', '空白测试企业', '规则测试企业']:
        scope = Scope(tenant_id='browser-test', organization_id='test', legal_entity_id=company,
                      ledger_id='test-ledger', accounting_period_id='2026-03', baseline_id=company+'-baseline')
        service.create_scope(scope)
        for user in ['readiness-operator', 'readiness-viewer']:
            if user != 'readiness-viewer' or company != '规则测试企业':
                grant_scope(db, user, scope)
        scopes.append(scope.model_dump())
    scope = Scope(**scopes[0])
    content = xlsx_fixture([('发票清单', [INVOICE_HEADERS,
        ['TEST-INVOICE-001', '2026-03-02', '100', '13', None, '测试供应商']])])
    artifact = service.create_artifact(ArtifactInput(scope=scope, filename='三月发票.xlsx', content_base64=base64.b64encode(content).decode()), actor_id='fixture')
    service.parse_artifact(scope, artifact_id=artifact['object_id'], expected_version=artifact['version'], actor_id='fixture', payload={'document_kind':'purchase_invoices'})
    prior = service.create_artifact(ArtifactInput(scope=scope, filename='二月承兑.xls', content_base64=base64.b64encode(b'not balances').decode(), observed_period='2026-02'), actor_id='fixture')
    rows = [['1001','库存现金','1000','0','1000','0','否',None],['4001','实收资本','0','1000','0','1000','否',None]]
    (root/'opening.xlsx').write_bytes(xlsx_fixture([('期初余额', [HEADERS,*rows])]))
    (root/'closing.xlsx').write_bytes(xlsx_fixture([('期末余额', [HEADERS,*rows])]))
    (root/'invoice.xlsx').write_bytes(content)
    (root/'broken.xlsx').write_bytes(b'not a workbook')
    # Real deterministic fixture preparation for an authenticated approval/voucher flow.
    rule_scope = Scope(**scopes[2])
    baseline_source = service.create_artifact(ArtifactInput(scope=rule_scope, filename='核对余额.xlsx',
        content_base64=base64.b64encode((root/'opening.xlsx').read_bytes()).decode(),
        observed_period='2026-02', source_purpose='opening_balance'), actor_id='fixture')
    comparison = service.baseline_candidate(rule_scope, balance_artifact_id=baseline_source['object_id'], close_artifact_id=baseline_source['object_id'])
    baseline = service.workbench(rule_scope)['baseline']
    service.confirm_baseline(rule_scope, actor_id='fixture', expected_version=baseline['version'],
                             payload={**comparison['confirmation_payload'], 'completeness_confirmed':True})
    fixtures = [
        ('purchase_invoices', [INVOICE_HEADERS,['TEST-VALID-001','2026-03-05','100','13','13%','供应商A']]),
        ('contract', [['合同编号','合同日期','供应商名称','合同金额'],['HT-001','2026-03-05','供应商A','113']]),
        ('stock_in', [['入库单号','入库日期','供应商名称','入库金额','存货名称'],['RK-001','2026-03-06','供应商A','113','模具配件']]),
        ('bank_statement', [['交易时间','支出金额','收入金额','对方户名','交易流水号','摘要'],['2026-03-06','113','0','供应商A','000123','付款']]),
    ]
    fact_ids = []
    for kind, data_rows in fixtures:
        artifact = service.create_artifact(ArtifactInput(scope=rule_scope, filename=kind+'.xlsx',
            content_base64=base64.b64encode(xlsx_fixture([('资料',data_rows)])).decode()), actor_id='fixture')
        result = service.parse_artifact(rule_scope, artifact_id=artifact['object_id'], expected_version=artifact['version'], actor_id='fixture',
            payload={'document_kind':kind, **({'bank_account_ref':'test-account'} if kind=='bank_statement' else {})})
        assert result['counts']['needs_review'] == 0
        fact_ids.extend(f['object_id'] for f in result['facts'])
    group = service.create_procurement_business(rule_scope, fact_ids=fact_ids, business_identity='合成采购001', actor_id='fixture')
    group = service.confirm_grouping(rule_scope, group_id=group['object_id'], expected_version=group['version'], actor_id='fixture')
    checks = service.reconcile_group(rule_scope, group_id=group['object_id'], actor_id='fixture')
    assert all(c['result']=='PASS' for c in checks), checks
    # Candidate data is explicitly seeded, no model/network call or mock-success audit.
    group = service.store.get_object(group['object_id'],rule_scope)
    definition = [{'debit_account':'库存商品','credit_account':'银行存款'}]
    candidate = service.store.create_initial_object('RuleCandidate',rule_scope,
        {'group_id':group['object_id'],'rule_definition':definition,'evidence_ids':group['data']['evidence_ids']},status='PROPOSED',created_by='fixture')
    card = service.store.create_initial_object('ConfirmationCard',rule_scope,
        {'group_id':group['object_id'],'candidate_id':candidate['object_id'],'suggested_rule':definition,
         'evidence_ids':group['data']['evidence_ids'],'impact_preview':{'period':'2026-03','group_count':1}},status='PENDING',created_by='fixture')
    (root/'fixture.json').write_text(json.dumps({'scopes':scopes, 'prior_id':prior['object_id'], 'card_id':card['object_id']}), encoding='utf-8')
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--port', required=True, type=int)
    args = parser.parse_args()
    if (args.root/'test.db').exists():
        raise SystemExit('Refusing to reuse an existing fixture database')
    uvicorn.run(build(args.root), host='127.0.0.1', port=args.port, log_level='warning')
