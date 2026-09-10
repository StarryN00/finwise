"""Explicit authorized suggestion generation; never confirms financial data."""
import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import build_opener, HTTPCookieProcessor, Request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from activate_problem_review import objects
from reparse_january_materials import copy_dataset, manifest
from import_juxianda_january import SCOPE
from app.db import utcnow
from app.ontology.store import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime-pid',type=int,required=True)
    args=p.parse_args();root=Path(__file__).resolve().parents[1]
    report=json.loads((root/'output/guidance-cards/isolated.json').read_text())
    assert report['preserved'] and report['model_calls'] and all(j['status']=='SUCCEEDED' for j in report['jobs'])
    import psutil
    runtime=psutil.Process(args.runtime_pid)
    assert Path(runtime.cwd())==root and runtime.cmdline()[-2:]==['--port','8767']
    env=runtime.environ();cmd=runtime.cmdline()
    db=Path(env['FINWISE_DATABASE_PATH']).resolve();storage=Path(env['FINWISE_STORAGE_PATH']).resolve()
    assert db.parent==root/'data/staging-juxianda-2026-01-from-2025' and storage==db.parent/'artifacts'
    before=objects(db);files=manifest(storage)
    protected={str(f):digest(f.read_bytes().hex()) for f in [root/'static/index.html',root/'static/app.js']}
    backup=root/'data/backups'/('pre-guidance-cards-'+utcnow().replace(':','-'))
    copy_dataset(db.parent,backup)
    assert objects(backup/'finwise.db')==before and manifest(backup/'artifacts')==files
    runtime.terminate();runtime.wait(timeout=15)
    fd,log=tempfile.mkstemp(prefix='finwise-guidance-cards-',suffix='.log')
    with os.fdopen(fd,'wb') as stream:
        child=subprocess.Popen(cmd,cwd=root,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    opener=build_opener(HTTPCookieProcessor());csrf=''
    def request(path,body=None):
        req=Request('http://127.0.0.1:8767/api/v1/'+path,data=json.dumps(body).encode() if body is not None else None,
                    headers={'Content-Type':'application/json','X-CSRF-Token':csrf})
        with opener.open(req,timeout=30) as response:return json.load(response)
    for _ in range(30):
        try:request('health');break
        except Exception:time.sleep(.5)
    else:raise RuntimeError('Restart failed; log '+log)
    tree=ast.parse((root/'scripts/run_juxianda_staging.py').read_text())
    password=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DEFAULT_PASSWORD' for t in n.targets))
    session=request('auth/login',{'username':env.get('FINWISE_STAGING_USER','juxianda-staging'),
                                 'password':env.get('FINWISE_STAGING_PASSWORD',password)})
    csrf=session['csrf_token'];initial=request('workbench',{'scope':SCOPE.model_dump()});period=initial['period']
    response=request('commands',{'scope':SCOPE.model_dump(),'action':'request_material_guidance',
        'target_id':period['object_id'],'target_version':period['version'],
        'idempotency_key':'authorized-guidance-cards-'+digest(before),'payload':{}})
    ids=[j['object_id'] for j in response['effect']['jobs']]
    for i in range(600):
        current=objects(db);jobs=[current[k] for k in ids]
        if all(j['status'] not in {'QUEUED','RUNNING'} for j in jobs):break
        if i%10==0:print(json.dumps({'pending':sum(j['status'] in {'QUEUED','RUNNING'} for j in jobs)}),flush=True)
        time.sleep(1)
    else:raise RuntimeError('Still running; do not resubmit')
    final=request('workbench',{'scope':SCOPE.model_dump()});after=objects(db)
    assert all(after.get(k)==v for k,v in before.items()),'Existing financial object changed'
    allowed={'MaterialGuidanceJob','MaterialGuidanceWatch','MaterialGuidanceTrigger','ModelRun'}
    assert all(o['object_type'] in allowed for k,o in after.items() if k not in before)
    assert manifest(storage)==files and all(digest(Path(k).read_bytes().hex())==v for k,v in protected.items())
    assert initial['material_review']['counts']==final['material_review']['counts']
    request('workbench',{'scope':SCOPE.model_dump()});time.sleep(2)
    assert objects(db)==after,'Read triggered a write'
    runs=[json.loads(o['data_json']) for k,o in after.items() if k not in before and o['object_type']=='ModelRun']
    output={'preserved':True,'backup':str(backup),'pid':child.pid,'log':log,
        'model_calls':sum(bool(r.get('gateway')) and r['gateway'].get('mock') is False for r in runs),
        'jobs':[{'id':j['object_id'],'status':j['status']} for j in jobs],
        'metadata':[r.get('gateway',{}) for r in runs],'counts':final['material_review']['counts']}
    (root/'output/guidance-cards/retained.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print(json.dumps({k:output[k] for k in ('preserved','backup','pid','model_calls','jobs')},ensure_ascii=False))


if __name__=='__main__':main()
