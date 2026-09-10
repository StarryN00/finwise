"""P0-P2 evidence on an isolated dataset; never modifies retained financial data."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reparse_january_materials import ROOT, SOURCE, copy_dataset, manifest
from import_juxianda_january import SCOPE
from app.config import Settings
from app.db import Database, utcnow
from app.ontology.store import ObjectStore, digest
from app.ontology.service import OntologyService
from app.parse_plan import KINDS, builtin, execute, packet
from app.parse_plans import PlanRequest
from app.tabular import read_workbook


def run(real=False):
    target = Path(tempfile.mkdtemp(prefix='finwise-structure-p2-')) / 'isolated'
    original_db_hash = hashlib.sha256((SOURCE/'finwise.db').read_bytes()).hexdigest()
    original_files = manifest(SOURCE/'artifacts')
    copy_dataset(SOURCE, target)
    settings = replace(Settings.from_env(ROOT), database_path=target/'finwise.db',
                       storage_path=target/'artifacts', environment='development', require_auth=False,
                       gateway_timeout_seconds=120, gateway_max_retries=0)
    if real:
        assert settings.agent_mode == 'gateway' and settings.deepseek_api_key, 'Real Gateway configuration required'
    service = OntologyService(ObjectStore(Database(settings)))
    store = service.store
    protected = lambda: digest([o for o in store.list_objects(None,SCOPE) if o['object_type'] != 'ParsePlan'])
    before = protected()
    rows, selections, expected = [], {}, {}
    artifacts = store.list_objects('SourceArtifact', SCOPE)
    for a in artifacts:
        kind = a['data'].get('parse_options',{}).get('document_kind')
        if kind not in KINDS or a['status'] != 'ACTIVE' or a['data'].get('observed_period') != SCOPE.accounting_period_id:
            continue
        content = (target/'artifacts'/a['data']['storage_path']).read_bytes()
        item = {'artifact_id':a['object_id'], 'document_kind':kind, 'source_version':a['version']}
        try:
            sheets = read_workbook(content)
            proposal = builtin(sheets,kind).model_dump()
            result = execute(content,proposal,kind,SCOPE.accounting_period_id)
            safe = packet(sheets,kind)
            assert a['data']['filename'] not in json.dumps(safe,ensure_ascii=False)
            item.update(status='PREVIEW',records=len(result['records']),
                        unresolved_rows=len(result['unresolved_rows']),checks=result['checks'],
                        apply_ready=result['apply_ready'],packet_hash=digest(safe))
            selections.setdefault(kind,a)
            expected.setdefault(kind,len(result['records']))
        except ValueError as exc:
            item.update(status='UNSUPPORTED_OR_NEEDS_STRUCTURE',reason=str(exc))
        rows.append(item)
    calls = []
    if real:
        for kind in sorted(KINDS):
            if kind not in selections:
                calls.append({'document_kind':kind,'status':'LOCAL_BLOCKED','gateway':{},
                              'preview_records':0,'expected_local_records':None,'apply_ready':False,
                              'reason':'没有可安全提交的结构样本，未调用模型'})
                continue
            a = selections[kind]
            response = service.parse_plans.request(PlanRequest(scope=SCOPE,stage='STRUCTURE_PLAN',
                artifact_id=a['object_id'],artifact_version=a['version'],document_kind=kind,
                idempotency_key='real-structure-'+kind), 'isolated-harness', 'accountant')
            job = response['object']
            calls.append({'document_kind':kind,'plan_id':job['object_id'],'status':job['status'],
                          'gateway':job['data'].get('gateway'),
                          'input_hash':job['data'].get('input_hash'),
                          'proposal_hash':digest(job['data'].get('proposal')),
                          'error':job['data'].get('error'),
                          'preview_records':len((job['data'].get('preview') or {}).get('records',[])),
                          'expected_local_records':expected[kind],
                          'apply_ready':(job['data'].get('preview') or {}).get('apply_ready',False),
                          'unresolved_rows':len((job['data'].get('preview') or {}).get('unresolved_rows',[]))})
    assert before == protected(), 'Financial objects changed in candidate-only harness'
    assert manifest(SOURCE/'artifacts') == original_files, 'Retained originals changed'
    current_db_hash = hashlib.sha256((SOURCE/'finwise.db').read_bytes()).hexdigest()
    report = {'harness':'structure-plan-p2-v1','timestamp':utcnow(),
              'isolated_database':str(target/'finwise.db'),'retained_database_unchanged':original_db_hash==current_db_hash,
              'originals_unchanged':True,'financial_objects_unchanged':True,'human_confirmations':0,
              'local_previews':rows,'model_calls':calls,'real_requested':real,
              'protected_objects_hash':before,'originals_manifest_hash':digest(original_files)}
    report['status'] = 'PASS' if (not real or all(c['status']=='REVIEW' and c['gateway'].get('mock') is False
        and c['preview_records']==c['expected_local_records'] and c['apply_ready'] for c in calls)) else 'REVIEW'
    out = ROOT/'output/structure-plan';out.mkdir(parents=True,exist_ok=True)
    filename = out/('real-harness.json' if real else 'local-harness.json')
    (out/('run-'+utcnow().replace(':','-')+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    filename.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'status':report['status'],'report':str(filename),'database':str(target/'finwise.db'),
                      'local_files':len(rows),'calls':[{k:v for k,v in c.items() if k!='gateway'} for c in calls]},ensure_ascii=False))
    return report


def replay_last_real():
    """Re-execute saved model pointers, with the Gateway disabled and zero writes."""
    source_report=ROOT/'output/structure-plan/real-harness.json'
    previous=json.loads(source_report.read_text())
    target=Path(previous['isolated_database']).parent
    settings=Settings(root=ROOT,database_path=target/'finwise.db',storage_path=target/'artifacts',require_auth=False)
    service=OntologyService(ObjectStore(Database(settings)))
    before=digest(service.store.list_objects(None,SCOPE));rows=[]
    for call in previous['model_calls']:
        job=service.store.get_object(call['plan_id'],SCOPE);data=job['data']
        a,content=service.parse_plans.source(SCOPE,data['artifact_id'],data['artifact_version'],data['document_kind'])
        result=execute(content,data['proposal'],data['document_kind'],SCOPE.accounting_period_id)
        rows.append({'document_kind':data['document_kind'],'model_request_status':job['status'],
            'plan_id':job['object_id'],'proposal_hash':digest(data['proposal']),
            'gateway':data['gateway'],'records':len(result['records']),
            'expected_records':call['expected_local_records'],'apply_ready':result['apply_ready'],
            'unresolved_rows':len(result['unresolved_rows']),'checks':result['checks']})
    assert before==digest(service.store.list_objects(None,SCOPE))
    report={'status':'PASS' if all(r['records']==r['expected_records'] and r['apply_ready'] and r['gateway']['mock'] is False for r in rows) else 'REVIEW',
        'harness':'saved-real-output-deterministic-replay-v1','timestamp':utcnow(),
        'model_calls_this_run':0,'financial_writes':0,'plan_writes':0,'human_confirmations':0,
        'source_report':str(source_report),'isolated_database':str(target/'finwise.db'),'files':rows}
    filename=ROOT/'output/structure-plan/real-replay.json'
    filename.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'status':report['status'],'report':str(filename),
                     'counts':{r['document_kind']:r['records'] for r in rows},'additional_model_calls':0},ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser();group=parser.add_mutually_exclusive_group()
    group.add_argument('--real',action='store_true');group.add_argument('--replay-last-real',action='store_true')
    args=parser.parse_args()
    replay_last_real() if args.replay_last_real else run(args.real)
