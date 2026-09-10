"""Read-only ActionType acceptance projection over an isolated dataset copy.

The selected code checkout is imported in a fresh process. The source database
is opened read-only, copied with SQLite backup, and every stored original is
hashed before and after deterministic replay. No command, model, confirmation,
or external integration is invoked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile


def file_manifest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob('*')) if path.is_file()
    }


def copy_dataset(source: Path, target: Path) -> None:
    target.mkdir(parents=True)
    with sqlite3.connect((source / 'finwise.db').as_uri() + '?mode=ro', uri=True) as src, \
            sqlite3.connect(target / 'finwise.db') as dst:
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    shutil.copytree(source / 'artifacts', target / 'artifacts')


def run(code_root: Path, source_data: Path) -> dict:
    code_root = code_root.resolve(strict=True)
    source_data = source_data.resolve(strict=True)
    sys.path.insert(0, str(code_root))

    from app.config import Settings
    from app.db import Database
    from app.ontology.contracts import Scope
    from app.ontology.service import OntologyService
    from app.ontology.store import ObjectStore, digest
    from app.tabular import ParseOptions, extract_workbook

    scope = Scope(
        tenant_id='juxianda-test', organization_id='kunshan-juxianda',
        legal_entity_id='kunshan-juxianda', ledger_id='chengyuan-ledger',
        accounting_period_id='2026-01', baseline_id='baseline-2026-01',
    )
    with tempfile.TemporaryDirectory(prefix='finwise-action-replay-') as temporary:
        target = Path(temporary) / 'isolated'
        copy_dataset(source_data, target)
        settings = Settings(root=code_root, database_path=target / 'finwise.db',
                            storage_path=target / 'artifacts', require_auth=False)
        service = OntologyService(ObjectStore(Database(settings)))
        originals_before = file_manifest(target / 'artifacts')
        objects_before = digest(service.store.list_objects(None, scope))
        workbench = service.workbench(scope)
        material = workbench['material_review']

        replayed = []
        for artifact in service.store.list_objects('SourceArtifact', scope):
            data = artifact['data']
            if artifact['status'] != 'ACTIVE' or data.get('observed_period') != scope.accounting_period_id \
                    or not data.get('parse_options'):
                continue
            entry = {'artifact_id': artifact['object_id'], 'filename': data.get('filename')}
            try:
                if data.get('plan_ref'):
                    result = service.parse_plans.replay(scope, artifact)
                elif data.get('payroll_mapping_id'):
                    result = service.payroll_mapping.replay(scope, artifact)
                else:
                    content = (target / 'artifacts' / data['storage_path']).read_bytes()
                    result = extract_workbook(content, ParseOptions(**data['parse_options']),
                                              scope.accounting_period_id)
                if data['parse_options']['document_kind'] == 'bank_statement':
                    result = service.bank_accounts.prepare(scope, artifact, result)
                entry.update(status='PASS', record_count=len(result.get('records', [])),
                             error_count=len(result.get('errors', [])))
            except Exception as exc:  # report per-file deterministic failures without mutating data
                entry.update(status='FAILED', error=type(exc).__name__ + ': ' + str(exc))
            replayed.append(entry)

        tasks = material.get('tasks', [])
        decision_v2 = [task for task in tasks if task.get('descriptor', {}).get('version') == 'decision-v2']
        four_question = [
            task for task in decision_v2
            if all((task['descriptor'].get('why') or {}).get(key)
                   for key in ('facts', 'rule', 'recommendation'))
            and task['descriptor'].get('why_now')
            and all(option.get('effects') for option in task['descriptor'].get('options', []))
        ]
        metrics = material.get('action_metrics') or {}
        try:
            from app.action_types import FALLBACK_IDS
            fallback_defined = len(FALLBACK_IDS)
        except ImportError:
            fallback_defined = 0
        return {
            'code_revision': code_root.name,
            'scope': scope.model_dump(),
            'artifact_count': len(service.store.list_objects('SourceArtifact', scope)),
            'fact_count': len(service.store.list_objects('FactRecord', scope)),
            'material_counts': material.get('counts'),
            'task_count': len(tasks),
            'triage_routes': {
                route: sum((task.get('triage') or {}).get('route') == route for task in tasks)
                for route in ('HUMAN', 'SYSTEM')
            },
            'decision_v2_count': len(decision_v2),
            'four_question_coverage': (
                round(len(four_question) / len(decision_v2), 4) if decision_v2 else 0
            ),
            'fallback_action_types_defined': fallback_defined,
            'action_metrics': metrics,
            'deterministic_replay': {
                'attempted': len(replayed),
                'passed': sum(item['status'] == 'PASS' for item in replayed),
                'failed': sum(item['status'] == 'FAILED' for item in replayed),
                'items': replayed,
            },
            'originals_unchanged': file_manifest(target / 'artifacts') == originals_before,
            'persisted_objects_unchanged': digest(service.store.list_objects(None, scope)) == objects_before,
            'model_calls': 0,
            'commands_executed': 0,
        }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--code-root', required=True, type=Path)
    parser.add_argument('--source-data', required=True, type=Path)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.code_root, arguments.source_data), ensure_ascii=False, indent=2))
