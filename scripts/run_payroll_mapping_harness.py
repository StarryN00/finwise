"""Real Gateway mapping validation: candidate-only, isolated by default."""
import argparse,json,os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reparse_january_materials import ROOT,SOURCE,copy_dataset,manifest
from import_juxianda_january import SCOPE
from app.config import Settings
from app.db import Database,utcnow
from app.ontology.store import ObjectStore,digest
from app.ontology.service import OntologyService
from app.payroll_mapping import structure_packet

def run(retained=False):
    backup=ROOT/'data/backups'/('pre-payroll-ai-'+utcnow().replace(':','-')) if retained else None
    target=SOURCE if retained else Path(tempfile.mkdtemp(prefix='finwise-payroll-ai-'))/'isolated'
    copy_dataset(SOURCE,backup if retained else target)
    settings=Settings.from_env(ROOT)
    from dataclasses import replace
    settings=replace(settings,database_path=target/'finwise.db',storage_path=target/'artifacts',require_auth=True,environment='staging',agent_mode='gateway',gateway_timeout_seconds=120)
    settings.validate_runtime()
    service=OntologyService(ObjectStore(Database(settings)));store=service.store
    protected=lambda:digest([o for o in store.list_objects(None,SCOPE) if o['object_type']!='PayrollMapping'])
    before=protected();originals=manifest(target/'artifacts')
    a=next(a for a in store.list_objects('SourceArtifact',SCOPE) if a['data']['filename']=='2026.1月聚贤达工资表.xls')
    _,sheets=service.payroll_mapping.source(SCOPE,a['object_id'])
    packet=structure_packet(sheets)
    assert a['data']['filename'] not in json.dumps(packet,ensure_ascii=False)
    response=service.execute_command(SCOPE,action='request_payroll_mapping',target_id=a['object_id'],target_version=a['version'],idempotency_key='payroll-real-'+utcnow(),actor_id='juxianda-staging',role='accountant')
    jid=response['effect']['object']['object_id']
    if response['effect']['object']['status']=='QUEUED':service.payroll_mapping.run_once()
    job=store.get_object(jid,SCOPE)
    assert protected()==before and manifest(target/'artifacts')==originals
    result={'status':job['status'],'job_id':jid,'database':str(target/'finwise.db'),'backup':str(backup) if backup else None,'human_confirmations':0,'unchanged_financial_objects':True,'gateway':job['data'].get('gateway'), 'error':job['data'].get('error'),'proposal':job['data'].get('proposal'),'preview_rows':len(job['data'].get('preview',{}).get('records',[]))}
    out=ROOT/'output/payroll-ai';out.mkdir(exist_ok=True,parents=True)
    (out/('retained.json' if retained else 'isolated.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    assert job['status']=='REVIEW' and job['data']['gateway']['mock'] is False
    assert len(job['data']['preview']['records'])==14,'Real payroll must retain exactly the 14 employees'

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--retained',action='store_true');args=p.parse_args();run(args.retained)
