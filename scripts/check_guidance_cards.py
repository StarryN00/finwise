"""Controlled real-model acceptance on an isolated copy, never on retained data."""
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
from app.material_guidance import GuidanceRequest, guidance


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime-pid',type=int,required=True)
    args=p.parse_args();import psutil
    root=Path(__file__).resolve().parents[1];runtime=psutil.Process(args.runtime_pid)
    assert Path(runtime.cwd())==root and runtime.cmdline()[-2:]==['--port','8767']
    for k,v in runtime.environ().items():
        if k.startswith('FINWISE_'):os.environ[k]=v
    original=Settings.from_env(root)
    assert original.database_path.parent.name=='staging-juxianda-2026-01-from-2025'
    isolated=Path(tempfile.mkdtemp(prefix='finwise-guidance-cards-'))/'dataset'
    copy_dataset(original.database_path.parent,isolated)
    settings=replace(original,database_path=isolated/'finwise.db',storage_path=isolated/'artifacts')
    svc=OntologyService(ObjectStore(Database(settings)))
    before={o['object_id']:o for o in svc.store.list_objects(None,SCOPE)};files=manifest(settings.storage_path)
    jobs=svc.material_guidance.enqueue(SCOPE,'juxianda-staging')['jobs']
    # No background worker: only this bounded queue is consumed.
    for _ in range(len(jobs)+4):
        if not svc.material_guidance.process_one():break
    wb=svc.workbench(SCOPE)
    task=next(t for t in wb['material_review']['tasks'] if t.get('bank_period'))
    response=guidance(svc,GuidanceRequest(scope=SCOPE,stage='MATERIAL_GUIDANCE',task_id=task['id'],
        descriptor_hash=task['descriptor']['fingerprint'],request_id='isolated-free-period-plan',
        user_text='按原交易日期归属'), 'juxianda-staging','accountant')
    assert response['status'] in {'PROPOSED','NEEDS_HUMAN'},response.get('message')
    after={o['object_id']:o for o in svc.store.list_objects(None,SCOPE)}
    assert all(after.get(k)==v for k,v in before.items()),'Existing object changed'
    assert manifest(settings.storage_path)==files
    runs=[o for k,o in after.items() if k not in before and o['object_type']=='ModelRun']
    successful=[r for r in runs if r['status']=='SUCCEEDED']
    assert successful and all(r['data']['gateway'].get('mock') is False for r in successful)
    assert len(successful)==len(jobs)+1,'Some guidance failed; inspect isolated report before activation'
    for run in successful:
        packet=json.dumps(run['data']['input_summary'],ensure_ascii=False)
        assert all(s not in packet for s in ('聚贤达','26322000000633306346','6893.93','15000.00'))
    # Re-reading and re-enqueueing identical evidence never produce new calls.
    snapshot=svc.store.list_objects(None,SCOPE);svc.workbench(SCOPE);svc.workbench(SCOPE)
    svc.material_guidance.enqueue(SCOPE,'juxianda-staging')
    assert not svc.material_guidance.process_one()
    assert snapshot==svc.store.list_objects(None,SCOPE)
    report={'isolated_path':str(isolated),'preserved':True,'model_calls':len(successful),
        'jobs':[{ 'id':j['object_id'],'status':svc.store.get_object(j['object_id'],SCOPE)['status']} for j in jobs],
        'calls':[{'id':r['object_id'],'status':r['status'],'metadata':r['data']['gateway']} for r in runs],
        'counts':wb['material_review']['counts']}
    out=root/'output/guidance-cards/isolated.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'preserved':True,'model_calls':len(successful),'report':str(out)},ensure_ascii=False))


if __name__=='__main__':main()
