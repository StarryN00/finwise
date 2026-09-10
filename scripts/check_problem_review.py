"""Explicit isolated rehearsal or retained review; never reparses source facts."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reparse_january_materials import copy_dataset, manifest
from import_juxianda_january import SCOPE
from app.config import Settings
from app.db import Database
from app.ontology.store import ObjectStore, digest
from app.ontology.service import OntologyService


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--runtime-pid',type=int,required=True)
    p.add_argument('--report',type=Path,required=True)
    args=p.parse_args()
    import psutil
    runtime=psutil.Process(args.runtime_pid)
    root=Path(__file__).resolve().parents[1]
    assert Path(runtime.cwd())==root and '8767' in runtime.cmdline()
    # Never print or persist inherited credentials.
    for k,v in runtime.environ().items():
        if k.startswith('FINWISE_'):os.environ[k]=v
    settings=Settings.from_env(root)
    assert settings.database_path.parent.name=='staging-juxianda-2026-01-from-2025'
    isolated=Path(tempfile.mkdtemp(prefix='finwise-problem-review-'))/'dataset'
    copy_dataset(settings.database_path.parent,isolated)
    settings=replace(settings,database_path=isolated/'finwise.db',storage_path=isolated/'artifacts')
    svc=OntologyService(ObjectStore(Database(settings)))
    before={o['object_id']:o for o in svc.store.list_objects(None,SCOPE)}
    hashes=manifest(settings.storage_path)
    initial=svc.workbench(SCOPE)
    period=initial['period']
    svc.execute_command(SCOPE,action='request_problem_review',target_id=period['object_id'],target_version=period['version'],
        idempotency_key='isolated-review-'+digest(before),actor_id='isolated-review',role='accountant',payload={})
    for _ in range(100):
        if not svc.problem_review.run_once():break
        jobs=svc.store.list_objects('ProblemReview',SCOPE)
        print(json.dumps({'finished':sum(j['status'] not in {'QUEUED','RUNNING'} for j in jobs),'total':len(jobs)}),flush=True)
    else:raise AssertionError('Review did not terminate')
    final=svc.workbench(SCOPE)
    after={o['object_id']:o for o in svc.store.list_objects(None,SCOPE)}
    assert all(after[k]==v for k,v in before.items()),'Existing object changed'
    assert manifest(settings.storage_path)==hashes,'Source changed'
    assert {o['object_type'] for k,o in after.items() if k not in before}<={'ProblemReview','ProblemReviewWatch','ProblemReviewTrigger','ModelRun'}
    for k in ('source_verified','accounting_usable','invoice_amount_confirmed','bill_confirmed'):
        assert initial['material_review']['counts'][k]==final['material_review']['counts'][k]
    runs=[o for o in after.values() if o['object_type']=='ModelRun' and o['data'].get('stage')=='PROBLEM_REVIEW']
    report={'isolated_path':str(isolated),'scope':SCOPE.model_dump(),'preserved':True,
        'source_snapshot':digest({'objects':before,'files':hashes}),
        'before':initial['material_review']['counts'],'after':final['material_review']['counts'],
        'jobs':final['problem_review']['jobs'],
        'model_calls':len(runs),'model_metadata':[r['data'].get('gateway',{}) for r in runs],
        'cost_note':'保留模型返回用量；供应商未返回费用时不估算实际扣费。'}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'report':str(args.report),'counts':final['problem_review']['counts'],'model_calls':len(runs),'preserved':True},ensure_ascii=False))


if __name__=='__main__':main()
