"""Controlled, six-file parser upgrade. Default: isolated copy, never retained data."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.db import Database,utcnow
from app.ontology.store import ObjectStore,digest
from app.ontology.service import OntologyService
from app.tabular import PARSER_VERSION
from import_juxianda_january import SCOPE

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'data/staging-juxianda-2026-01-from-2025'
NAMES={
 '2026.1月聚贤达泰隆银行保证金流水.xls':14,
 '2026.1月聚贤达中国银行流水.pdf':1,
 '2026.1月聚贤达医保单位缴费明细.xls':3,
 '2026.1月聚贤达泰隆银行应收电子承兑明细表.xls':2,
 '2026.1月聚贤达泰隆银行应付电子承兑明细表.xls':4,
 '2026.1月聚贤达泰隆银行应付银行申请电子承兑明细表.xls':4,
}

def copy_dataset(source,target):
    target.mkdir(parents=True,exist_ok=False)
    with sqlite3.connect((source/'finwise.db').as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(target/'finwise.db') as dst:
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    shutil.copytree(source/'artifacts',target/'artifacts')

def manifest(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}

def run(apply_retained=False):
    source=SOURCE.resolve(strict=True)
    if apply_retained:
        backup=ROOT/'data/backups'/('pre-material-v3-'+utcnow().replace(':','-'))
        copy_dataset(source,backup);target=source
    else:
        backup=None;target=Path(tempfile.mkdtemp(prefix='finwise-material-upgrade-'))/'isolated'
        copy_dataset(source,target)
    db=Database(Settings(root=ROOT,database_path=target/'finwise.db',storage_path=target/'artifacts'))
    service=OntologyService(ObjectStore(db));store=service.store
    artifacts=store.list_objects('SourceArtifact',SCOPE)
    selected=[a for a in artifacts if a['data']['filename'] in NAMES]
    assert len(selected)==6 and len({a['data']['filename'] for a in selected})==6
    assert all(a['data']['observed_period']=='2026-01' and a['data'].get('parse_status')=='FAILED' and a['data'].get('parse_version')!=PARSER_VERSION for a in selected),'Only six failed old-version originals may be upgraded once'
    protected=lambda:[o for o in store.list_objects(None,SCOPE) if o['object_type'] not in {'SourceArtifact','FactRecord'}]
    protected_before=digest(protected());originals=manifest(target/'artifacts');results=[]
    for a in selected:
        result=service.execute_command(SCOPE,action='parse_artifact',target_id=a['object_id'],target_version=a['version'],idempotency_key='jan-material-v3-'+a['object_id'],actor_id='january-material-parser-upgrade',role='accountant',payload=a['data']['parse_options'])
        effect=result['effect'];parsed=effect['artifact'];facts=effect['facts']
        assert len(facts)==NAMES[a['data']['filename']] and parsed['data']['parse_status']!='FAILED'
        assert parsed['version']>a['version'] and parsed['data']['sha256']==a['data']['sha256']
        results.append({'filename':a['data']['filename'],'artifact_id':a['object_id'],'before_version':a['version'],'after_version':parsed['version'],'counts':effect['counts'],'checks':parsed['data'].get('parse_checks',{})})
    overview=service.workbench(SCOPE)
    assert digest(protected())==protected_before,'Existing decisions or financial objects changed'
    assert manifest(target/'artifacts')==originals,'Original files changed'
    assert len(store.list_objects('SourceArtifact',SCOPE))==17
    assert overview['material_review']['counts']['records']==232
    assert overview['material_review']['counts']['source_verified']==0
    assert overview['material_review']['counts']['accounting_usable']==0
    assert overview['baseline']['status']=='DRAFT'
    report={'status':'PASS','mode':'retained' if apply_retained else 'isolated','database':str(target/'finwise.db'),'backup':str(backup) if backup else None,'parser_version':PARSER_VERSION,'scope':SCOPE.model_dump(),'counts':overview['material_review']['counts'],'files':results,'protected_objects_hash':protected_before,'originals_manifest_hash':digest(originals),'human_verifications_submitted':0,'model_calls':0,'timestamp':utcnow()}
    out=ROOT/'output/material-upgrade';out.mkdir(parents=True,exist_ok=True)
    (out/('retained.json' if apply_retained else 'isolated.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--apply-retained',action='store_true');args=p.parse_args();run(args.apply_retained)
