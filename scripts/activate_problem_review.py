"""Explicit local staging activation after isolated review; no financial commands."""
import argparse
import ast
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import build_opener, HTTPCookieProcessor, Request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reparse_january_materials import copy_dataset, manifest
from import_juxianda_january import SCOPE
from app.db import utcnow
from app.ontology.store import digest


def objects(database):
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row
        return {r['object_id']:dict(r) for r in c.execute('SELECT o.* FROM ontology_objects o WHERE version=(SELECT max(version) FROM ontology_objects v WHERE v.object_id=o.object_id)')}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--runtime-pid',type=int,required=True)
    p.add_argument('--isolated-report',type=Path,required=True)
    args=p.parse_args()
    report=json.loads(args.isolated_report.read_text())
    assert report['preserved'] and report['model_calls'] and all(j['status'] not in {'FAILED','QUEUED','RUNNING'} for j in report['jobs'])
    import psutil
    runtime=psutil.Process(args.runtime_pid);root=Path(__file__).resolve().parents[1]
    assert Path(runtime.cwd())==root and runtime.cmdline()[-2:]==['--port','8767']
    environment=runtime.environ();cmd=runtime.cmdline()
    database=Path(environment['FINWISE_DATABASE_PATH']).resolve()
    storage=Path(environment['FINWISE_STORAGE_PATH']).resolve()
    assert database.parent==root/'data/staging-juxianda-2026-01-from-2025' and storage==database.parent/'artifacts'
    before=objects(database);files=manifest(storage)
    protected_files={str(f):digest(f.read_bytes().hex()) for f in [root/'static/index.html',root/'static/app.js']}
    backup=root/'data/backups'/('pre-problem-review-'+utcnow().replace(':','-'))
    copy_dataset(database.parent,backup)
    assert objects(backup/'finwise.db')==before and manifest(backup/'artifacts')==files
    runtime.terminate();runtime.wait(timeout=15)
    fd,log=tempfile.mkstemp(prefix='finwise-problem-review-',suffix='.log')
    with os.fdopen(fd,'wb') as output:
        child=subprocess.Popen(cmd,cwd=root,env=environment,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    opener=build_opener(HTTPCookieProcessor());csrf=''
    def request(path,body=None):
        req=Request('http://127.0.0.1:8767/api/v1/'+path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type':'application/json','X-CSRF-Token':csrf})
        with opener.open(req,timeout=30) as response:return json.load(response)
    for _ in range(30):
        try:request('health');break
        except Exception:time.sleep(.5)
    else:raise RuntimeError('Service health check failed; see '+log)
    tree=ast.parse((root/'scripts/run_juxianda_staging.py').read_text())
    default=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DEFAULT_PASSWORD' for t in n.targets))
    session=request('auth/login',{'username':environment.get('FINWISE_STAGING_USER','juxianda-staging'),
        'password':environment.get('FINWISE_STAGING_PASSWORD',default)})
    csrf=session['csrf_token']
    initial=request('workbench',{'scope':SCOPE.model_dump()});assert 'problem_review' in initial
    period=initial['period']
    request('commands',{'scope':SCOPE.model_dump(),'action':'request_problem_review','target_id':period['object_id'],
        'target_version':period['version'],'idempotency_key':'authorized-problem-review-'+digest(before),'payload':{}})
    final=None
    for i in range(600):
        final=request('workbench',{'scope':SCOPE.model_dump()})
        jobs=final['problem_review']['jobs']
        if jobs and all(j['status'] not in {'QUEUED','RUNNING'} for j in jobs):break
        if i%10==0:print(json.dumps({'pending':sum(j['status'] in {'QUEUED','RUNNING'} for j in jobs)}),flush=True)
        time.sleep(1)
    else:raise RuntimeError('Review still pending; do not resubmit')
    after=objects(database)
    assert all(after.get(k)==v for k,v in before.items()),'Existing finance object changed'
    allowed={'ProblemReview','ProblemReviewWatch','ProblemReviewTrigger','ModelRun'}
    assert all(o['object_type'] in allowed for k,o in after.items() if k not in before)
    assert files==manifest(storage)
    assert all(digest(Path(k).read_bytes().hex())==v for k,v in protected_files.items())
    for key in ('source_verified','accounting_usable','invoice_amount_confirmed','bill_confirmed'):
        assert initial['material_review']['counts'][key]==final['material_review']['counts'][key]
    runs=[json.loads(o['data_json']) for k,o in after.items() if k not in before and o['object_type']=='ModelRun']
    out=root/'output/problem-review/retained.json'
    out.write_text(json.dumps({'backup':str(backup),'pid':child.pid,'log':log,'preserved':True,
        'before':initial['material_review']['counts'],'after':final['material_review']['counts'],
        'jobs':jobs,'model_calls':len(runs),'metadata':[r.get('gateway',{}) for r in runs]},ensure_ascii=False,indent=2))
    print(json.dumps({'backup':str(backup),'pid':child.pid,'preserved':True,'counts':final['problem_review']['counts'],'report':str(out)},ensure_ascii=False))


if __name__=='__main__':main()
