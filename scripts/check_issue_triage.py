"""Isolated, read-only regression of routing; no commands or model calls."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reparse_january_materials import copy_dataset, manifest
from import_juxianda_january import SCOPE
from app.config import Settings
from app.db import Database
from app.ontology.store import ObjectStore
from app.ontology.service import OntologyService


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime-pid',type=int,required=True)
    args=p.parse_args()
    import psutil
    root=Path(__file__).resolve().parents[1];runtime=psutil.Process(args.runtime_pid)
    assert Path(runtime.cwd())==root and runtime.cmdline()[-2:]==['--port','8767']
    for k,v in runtime.environ().items():
        if k.startswith('FINWISE_'):os.environ[k]=v
    settings=Settings.from_env(root)
    assert settings.database_path.parent.name=='staging-juxianda-2026-01-from-2025'
    isolated=Path(tempfile.mkdtemp(prefix='finwise-issue-triage-'))/'dataset'
    copy_dataset(settings.database_path.parent,isolated)
    settings=replace(settings,database_path=isolated/'finwise.db',storage_path=isolated/'artifacts')
    svc=OntologyService(ObjectStore(Database(settings)))
    def no_model(*args,**kwargs):raise AssertionError('Read triggered model')
    svc.gateway.complete=no_model
    before=svc.store.list_objects(None,SCOPE);files=manifest(settings.storage_path)
    wb=svc.workbench(SCOPE);again=svc.workbench(SCOPE)
    assert wb==again and before==svc.store.list_objects(None,SCOPE) and files==manifest(settings.storage_path)
    m=wb['material_review'];c=m['counts']
    assert c['human_issue_tasks']+c['system_issue_tasks']==c['issue_tasks']
    assert all(t['triage']['questions'] and t['triage']['human_ready'] for t in m['tasks'] if t['triage']['route']=='HUMAN')
    assert all(not t['triage']['questions'] for t in m['tasks'] if t['triage']['route']=='SYSTEM')
    report={'isolated_path':str(isolated),'preserved':True,'model_calls':0,'counts':c,
            'issues':[t for t in m['tasks'] if t['kind']!='VERIFY'],'overview':wb}
    out=root/'output/issue-triage/isolated.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'preserved':True,'model_calls':0,'counts':c,'report':str(out)},ensure_ascii=False))


if __name__=='__main__':main()
