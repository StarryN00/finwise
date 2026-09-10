"""Compare all January sources, then refresh only stale unbound results.

Default: isolated rehearsal. --apply-retained requires its exact inventory token.
No model requests, source edits, manual confirmations, or parser bypass payloads.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reparse_january_materials import ROOT, SOURCE, copy_dataset, manifest
from import_juxianda_january import SCOPE
from app.config import Settings
from app.db import Database, utcnow
from app.ontology.store import ObjectStore, digest
from app.ontology.service import OntologyService
from app.tabular import extract_workbook, ParseOptions, PARSER_VERSION

FIELDS = ('source_anchor', 'record_type', 'normalized_value', 'original_value',
          'field_sources', 'extraction_issues', 'period_check')


def projected(row):
    return {k: row.get(k) for k in FIELDS}


def all_current_objects(service):
    with service.store.database.connect() as connection:
        return {row['object_id']: dict(row) for row in connection.execute(
            'SELECT o.* FROM ontology_objects o WHERE version=(SELECT max(version) FROM ontology_objects v WHERE v.object_id=o.object_id) ORDER BY object_id')}


def inventory_token(service, items):
    return digest({'objects':all_current_objects(service), 'inventory':items,
                   'files':manifest(service.store.database.settings.storage_path)})


def inventory(service, scope):
    items = []
    for a in service.store.list_objects('SourceArtifact', scope):
        d = a['data']
        if (a['status'] != 'ACTIVE' or d.get('observed_period') != scope.accounting_period_id
                or d.get('source_purpose') in {'historical_reference','opening_balance','prior_close'}
                or not d.get('parse_options')):
            continue
        assert service.materials.source_valid(a), 'Original hash/path invalid'
        if d.get('plan_ref'):
            result = service.parse_plans.replay(scope, a)
        elif d.get('payroll_mapping_id'):
            result = service.payroll_mapping.replay(scope, a)
        else:
            result = extract_workbook((service.store.database.settings.storage_path/d['storage_path']).read_bytes(),
                                      ParseOptions(**d['parse_options']), scope.accounting_period_id)
        if d['parse_options']['document_kind'] == 'bank_statement':
            result = service.bank_accounts.prepare(scope, a, result)
            if d.get('bank_account_binding'):
                old_binding = d['bank_account_binding']; new_binding = result.get('bank_account_binding', {})
                assert all(new_binding.get(k) == old_binding.get(k) for k in ('account_id','account_version')), 'Bank assignment would change'
                old_reference = old_binding.get('account_reference') or old_binding.get('account_number') or old_binding.get('identity',{}).get('account_number')
                assert new_binding.get('account_reference') == old_reference, 'Bank reference would change'
        assert not result.get('errors') and result.get('checks', {}).get('overall') != 'REVIEW', 'Current parser requires investigation'
        old = [service.store.get_object(i, scope)['data'] for i in d.get('parsed_fact_ids', [])]
        new = result['records']
        changed = [projected(r) for r in old] != [projected(r) for r in new]
        old_index = {digest(r['source_anchor']): r for r in old}
        new_index = {digest(r['source_anchor']): r for r in new}
        assert len(new_index) == len(new), 'Ambiguous duplicate source anchors'
        # This maintenance run only removes classified references/enriches sources.
        for k, r in new_index.items():
            assert k in old_index, 'Unexpected new transaction'
            previous = dict(old_index[k]['normalized_value'])
            if d.get('bank_account_binding') and previous.get('bank_name') is None:
                account = next(x for x in service.bank_accounts.accounts(scope) if x['object_id']==d['bank_account_binding']['account_id'])
                assert r['normalized_value'].get('bank_name') == account['data']['bank_name'], 'Bank label must come from existing registry'
                previous['bank_name'] = account['data']['bank_name']
            assert r['normalized_value'] == previous, 'Business values would change'
        references = {(s['sheet'], row['row']) for s in result.get('sheets', []) for row in s.get('reference_rows', [])}
        removed = [r for k, r in old_index.items() if k not in new_index]
        assert all((r['original_value']['sheet'], r['source_anchor']['row']) in references for r in removed), 'Removed row is not a classified source reference'
        if changed:
            assert not d.get('plan_ref') and not d.get('payroll_mapping_id'), 'Bound plan needs its explicit review workflow'
            assert d.get('parse_version') != PARSER_VERSION, 'Same-version difference needs explicit investigation'
        items.append({'artifact_id':a['object_id'], 'filename':d['filename'], 'version':a['version'],
                      'sha256':d['sha256'], 'parser_before':d.get('parse_version'), 'update':changed,
                      'before_count':len(old), 'after_count':len(new), 'removed_rows':[r['source_anchor'] for r in removed],
                      'result_hash':digest([projected(r) for r in new]), 'checks':result.get('checks',{}),
                      'options':d['parse_options']})
    return items


def refresh(service, scope, expected_inventory):
    with service.store.database.transaction():
        current = inventory(service, scope)
        assert digest(current) == digest(expected_inventory), 'Inventory changed; repeat isolated rehearsal'
        before = service.store.list_objects(None, scope)
        targets = {i['artifact_id'] for i in current if i['update']}
        mutable = {o['object_id'] for o in before if o['object_id'] in targets or
                   o['object_type']=='FactRecord' and o['data'].get('source_artifact_id') in targets}
        protected = {o['object_id']:o for o in before if o['object_id'] not in mutable}
        effects = []
        for item in current:
            if not item['update']:
                continue
            result = service.execute_command(scope, action='parse_artifact', target_id=item['artifact_id'],
                target_version=item['version'], idempotency_key='authorized-parser-refresh-'+digest(item),
                actor_id='authorized-parser-refresh', role='accountant', payload=item['options'])
            effect = result['effect']; a=effect['artifact']
            assert a['version']==item['version']+1 and a['data']['sha256']==item['sha256']
            assert digest([projected(f['data']) for f in effect['facts']])==item['result_hash'], 'Applied result differs from rehearsal'
            effects.append({'artifact_id':a['object_id'],'filename':item['filename'],'before_version':item['version'],
                            'after_version':a['version'],'before_count':item['before_count'],'after_count':len(effect['facts']),
                            'removed_rows':item['removed_rows']})
        after = {o['object_id']:o for o in service.store.list_objects(None, scope)}
        assert all(after.get(k)==v for k,v in protected.items()), 'Protected decisions or downstream objects changed; rolled back'
        assert all(o['object_id'] in {v['object_id'] for v in before} for o in after.values()), 'Unexpected new financial objects'
        assert not any(i['update'] for i in inventory(service, scope)), 'Stale results remain'
        return effects


def apply_checked(service, scope, expected_token):
    with service.store.database.transaction():
        items = inventory(service, scope)
        assert inventory_token(service, items)==expected_token, 'Full snapshot changed; repeat rehearsal'
        before_objects=all_current_objects(service)
        targets={i['artifact_id'] for i in items if i['update']}
        mutable={k for k,o in before_objects.items() if k in targets or
                 o['object_type']=='FactRecord' and json.loads(o['data_json']).get('source_artifact_id') in targets}
        files=manifest(service.store.database.settings.storage_path)
        before_view=service.workbench(scope)
        effects=refresh(service, scope, items)
        after_view=service.workbench(scope)
        after_objects=all_current_objects(service)
        assert set(after_objects)==set(before_objects), 'Unexpected object creation'
        assert all(after_objects[k]==v for k,v in before_objects.items() if k not in mutable), 'Other scopes or protected decisions changed'
        assert manifest(service.store.database.settings.storage_path)==files, 'Originals changed'
        for key in ('source_verified','accounting_usable'):
            assert before_view['material_review']['counts'][key]==after_view['material_review']['counts'][key], 'Financial eligibility changed'
        return effects, before_view, after_view


def run(apply_retained=False, expected_token=None):
    target = Path(tempfile.mkdtemp(prefix='finwise-refresh-rehearsal-'))/'isolated'
    backup = None
    if apply_retained:
        assert expected_token, 'Supply the isolated inventory token'
        target = SOURCE
    else:
        copy_dataset(SOURCE, target)
    service = OntologyService(ObjectStore(Database(Settings(root=ROOT, database_path=target/'finwise.db', storage_path=target/'artifacts'))))
    items = inventory(service, SCOPE)
    token = inventory_token(service, items)
    if apply_retained:
        assert token==expected_token, 'Retained data changed after rehearsal'
        backup = ROOT/'data/backups'/('pre-parsing-refresh-'+utcnow().replace(':','-'))
        copy_dataset(SOURCE, backup)
    effects, before_view, after_view = apply_checked(service, SCOPE, token)
    report = {'mode':'retained' if apply_retained else 'isolated','status':'PASS','timestamp':utcnow(),
              'inventory_token':token,'database':str(target/'finwise.db'),'backup':str(backup) if backup else None,
              'files_checked':len(items),'inventory':items,'updates':effects,
              'before_counts':before_view['material_review']['counts'],'after_counts':after_view['material_review']['counts'],
              'remaining_tasks':[{'title':t['title'],'filename':t['filename'],'kind':t['kind'],'reason':t['reason'],'deferred':t['deferred']}
                                 for t in after_view['material_review']['tasks'] if t['kind']!='VERIFY'],
              'originals_unchanged':True,'protected_objects_unchanged':True,'model_calls':0,'human_confirmations':0}
    output=ROOT/'output/parsing-refresh';output.mkdir(parents=True,exist_ok=True)
    path=output/('retained.json' if apply_retained else 'isolated.json')
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'status':report['status'],'report':str(path),'token':token,'updates':effects,'counts':report['after_counts'],'backup':report['backup']},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--apply-retained',action='store_true');p.add_argument('--expected-token');args=p.parse_args()
    run(args.apply_retained,args.expected_token)
