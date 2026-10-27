"""Isolated real HTTP fixture for settings UI; never calls a real model.

Use a fresh --root for each acceptance run. All identities, enterprises, source
files and vouchers are synthetic, and all mutations use the normal app APIs.
The third enterprise stays queued until the operator pauses it, to make the
running-task guard deterministic during browser acceptance.
"""
import argparse
import base64
from io import BytesIO
from pathlib import Path
import sys
import time

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.auth import create_user, grant_scope
from app.autonomous_checks import validate
from app.autonomous_runtime import prepare
from app.bookkeeping_profile import profile_reference
from app.config import Settings
from app.main import create_app
from app.ontology.contracts import ArtifactInput, Scope
from app.review_loop import REVIEW_POLICY_VERSION


ACCOUNTS = {
    'settings-tester': ('settings-test-password', 'accountant'),
    'settings-viewer': ('settings-view-password', 'viewer'),
    'settings-empty': ('settings-empty-password', 'accountant'),
}


def build(root: Path):
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    database_path = root / 'settings-fixture.sqlite'
    if database_path.exists():
        raise ValueError('Use a fresh --root; this fixture never resets an existing database.')
    settings = Settings(
        root=ROOT, database_path=database_path, storage_path=root / 'sources',
        require_auth=True, autonomous_enabled=True, agent_send_full_records=True,
        autonomous_codex_path='/usr/bin/true', autonomous_claude_path='/usr/bin/true',
        autonomous_model='settings-fixture-codex',
        autonomous_claude_model='settings-fixture-claude',
    )
    app = create_app(settings)
    service = app.state.service
    workflow = service.autonomous
    for username, (password, role) in ACCOUNTS.items():
        create_user(app.state.database, username, password, role)

    scopes = [Scope(
        tenant_id='settings-ui-test', organization_id='settings-ui-test',
        legal_entity_id=company, ledger_id=ledger, accounting_period_id='2026-03',
        baseline_id=baseline,
    ) for company, ledger, baseline in [
        ('设置验收甲企业', '甲企业账套', 'settings-a'),
        ('设置验收乙企业', '乙企业账套', 'settings-b'),
        ('设置验收处理中企业', '处理中账套', 'settings-active'),
    ]]
    for scope in scopes:
        service.create_scope(scope)
        for username in ('settings-tester', 'settings-viewer'):
            grant_scope(app.state.database, username, scope)

    workflow.save_bookkeeping_profile(
        scopes[1], 'settings-tester', 'accountant', mode='ORIGINAL', expected_version=0)

    def analyst(folder, manifest, paths, context, run_settings, heartbeat, progress):
        # The same simulated accounting output is revalidated after each setting
        # change, including the current profile reference and independent review.
        source_id = manifest['sources'][0]['id']
        ref = {'source_id': source_id, 'sheet': 'Sheet', 'row': 2}
        profile = profile_reference(context['bookkeeping_profile'])
        delivery = {
            'period': manifest['period'], 'mode': 'SOURCE_BOOKKEEPING',
            'source_roles': {source_id: '银行资料'}, 'bindings': {}, 'opening': [],
            'entries': [dict(voucher='候选001', date='2026-03-01', code=code,
                             name=name, memo='验收用股东投入', debit=debit,
                             credit=credit, source=ref)
                        for code, name, debit, credit in [
                            ('1002', '银行存款', '100.00', '0.00'),
                            ('4001', '实收资本', '0.00', '100.00'),
                        ]],
            'findings': [],
            'voucher_assessments': [{
                'voucher': '候选001', 'status': 'READY_FOR_REVIEW',
                'reason': '模拟原件支持，等待人工复核', 'evidence': [ref],
                'finding_ids': [], 'bookkeeping_profile': profile,
            }],
            'report': '隔离界面验收：模拟银行原件和处理结果，仅供测试，不属于真实企业账务。' * 10,
            'bank': [dict(source=ref, date='2026-03-01', income='100.00', expense='0.00')],
            'invoices': [], 'settlement_matches': [], 'employee_reimbursements': [],
            'unassigned_reimbursement_invoices': [], 'bookkeeping_profile': profile,
        }
        workspace, _ = prepare(folder, manifest, paths, context, run_settings)
        mechanical = validate(workspace, manifest, delivery, {}, context)
        assert mechanical['passed'], mechanical['errors']
        return {
            'review_policy_version': REVIEW_POLICY_VERSION,
            'delivery': delivery, 'mechanical': mechanical,
            'review': {
                'verdict': 'pass', 'defects': [], 'ready_vouchers': ['候选001'],
                'reviewed_bookkeeping_profile': profile,
                'reviewed_employee_reimbursements': [], 'reviewed_settlement_matches': [],
                'reviewed_decisions': [], 'reviewed_revisions': [], 'reviewed_responses': [],
                'coverage': [{'area': '投入', 'evidence': [ref], 'conclusion': '模拟原件一致'}],
            },
        }

    workflow.runner = analyst
    book = openpyxl.Workbook()
    book.active.append(['日期', '摘要', '收入', '支出'])
    book.active.append(['2026-03-01', '验收用股东投入', 100, 0])
    stream = BytesIO()
    book.save(stream)
    for index, scope in enumerate(scopes):
        service.create_artifact(ArtifactInput(
            scope=scope, filename='隔离验收银行.xlsx',
            content_base64=base64.b64encode(stream.getvalue()).decode(),
        ), actor_id='settings-tester')
        job = workflow.current(scope)
        queued_at = time.time() - 6 if index < 2 else time.time() + 86400
        workflow._revise(scope, job, job['status'], {'queued_at': queued_at})
        if index < 2:
            assert workflow.tick(scope), workflow.current(scope)['data']['message']

    # Only the simulated autonomous worker is enabled. No legacy/model workers
    # can consume these test artifacts, even if local environment variables exist.
    for worker in [service.historical, service.payroll_mapping, service.problem_review,
                   service.material_agent, app.state.monthly_agent]:
        worker.start = lambda: None
    app.state.settings_fixture_scopes = scopes
    return app


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8798)
    args = parser.parse_args()
    uvicorn.run(build(args.root), host='127.0.0.1', port=args.port)
