"""Back up and restart only the verified local January service; no commands."""
import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import build_opener, HTTPCookieProcessor, Request

from activate_problem_review import objects
from reparse_january_materials import copy_dataset, manifest
from import_juxianda_january import SCOPE
from app.db import utcnow
from app.ontology.store import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime-pid',type=int,required=True)
    args=p.parse_args();root=Path(__file__).resolve().parents[1]
    report=json.loads((root/'output/issue-triage/isolated.json').read_text())
    assert report['preserved'] and report['model_calls']==0
    import psutil
    runtime=psutil.Process(args.runtime_pid)
    assert Path(runtime.cwd())==root and runtime.cmdline()[-2:]==['--port','8767']
    environment=runtime.environ();cmd=runtime.cmdline()
    db=Path(environment['FINWISE_DATABASE_PATH']).resolve();storage=Path(environment['FINWISE_STORAGE_PATH']).resolve()
    assert db.parent==root/'data/staging-juxianda-2026-01-from-2025' and storage==db.parent/'artifacts'
    before=objects(db);files=manifest(storage)
    protected={str(f):digest(f.read_bytes().hex()) for f in [root/'static/index.html',root/'static/app.js']}
    backup=root/'data/backups'/('pre-issue-triage-'+utcnow().replace(':','-'))
    copy_dataset(db.parent,backup)
    assert objects(backup/'finwise.db')==before and manifest(backup/'artifacts')==files
    runtime.terminate();runtime.wait(timeout=15)
    fd,log=tempfile.mkstemp(prefix='finwise-issue-triage-',suffix='.log')
    with os.fdopen(fd,'wb') as output:
        child=subprocess.Popen(cmd,cwd=root,env=environment,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    opener=build_opener(HTTPCookieProcessor());csrf=''
    def request(path,body=None):
        req=Request('http://127.0.0.1:8767/api/v1/'+path,data=json.dumps(body).encode() if body is not None else None,
                    headers={'Content-Type':'application/json','X-CSRF-Token':csrf})
        with opener.open(req,timeout=30) as response:return json.load(response)
    for _ in range(30):
        try:request('health');break
        except Exception:time.sleep(.5)
    else:raise RuntimeError('Restart failed; check '+log)
    tree=ast.parse((root/'scripts/run_juxianda_staging.py').read_text())
    password=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DEFAULT_PASSWORD' for t in n.targets))
    session=request('auth/login',{'username':environment.get('FINWISE_STAGING_USER','juxianda-staging'),
                                 'password':environment.get('FINWISE_STAGING_PASSWORD',password)})
    csrf=session['csrf_token']
    wb=request('workbench',{'scope':SCOPE.model_dump()});time.sleep(3)
    again=request('workbench',{'scope':SCOPE.model_dump()})
    assert wb['material_review']==again['material_review']
    assert before==objects(db),'Read/restart changed stored objects'
    assert files==manifest(storage)
    assert all(digest(Path(k).read_bytes().hex())==v for k,v in protected.items())
    c=wb['material_review']['counts'];assert c['human_issue_tasks']+c['system_issue_tasks']==c['issue_tasks']
    out=root/'output/issue-triage/retained.json'
    out.write_text(json.dumps({'preserved':True,'model_calls':0,'backup':str(backup),'pid':child.pid,'log':log,
                              'counts':c,'tasks':[t for t in wb['material_review']['tasks'] if t['kind']!='VERIFY']},ensure_ascii=False,indent=2))
    print(json.dumps({'preserved':True,'model_calls':0,'backup':str(backup),'pid':child.pid,'counts':c},ensure_ascii=False))


if __name__=='__main__':main()
