"""Re-read only January invoice/payroll sources after a verified parser upgrade.

Default is a disposable copy. The explicit retained mode first takes a complete
SQLite/attachment backup. No human verification or financial command is issued.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reparse_january_materials import ROOT,SOURCE,copy_dataset,manifest
from import_juxianda_january import SCOPE
from app.config import Settings
from app.db import Database,utcnow
from app.ontology.store import ObjectStore,digest
from app.ontology.service import OntologyService
from app.tabular import PARSER_VERSION

NAMES={'聚贤达1月进项.xlsx':'purchase_invoices','聚贤达1月销项.xlsx':'sales_invoices',
       '2026.1月聚贤达工资表.xls':'payroll'}


def run(retained=False):
    stamp=utcnow().replace(':','-')
    backup=ROOT/'data/backups'/('pre-material-clarity-'+stamp) if retained else None
    target=SOURCE if retained else Path(tempfile.mkdtemp(prefix='finwise-clarity-'))/'isolated'
    copy_dataset(SOURCE,backup if retained else target)
    db=Database(Settings(root=ROOT,database_path=target/'finwise.db',storage_path=target/'artifacts'))
    service=OntologyService(ObjectStore(db));store=service.store
    originals=manifest(target/'artifacts')
    # The assertions and all commands share a transaction: any failed guard rolls back.
    with db.transaction():
        artifacts=store.list_objects('SourceArtifact',SCOPE)
        selected=[a for a in artifacts if a['data']['filename'] in NAMES]
        assert len(selected)==len(NAMES) and len({a['data']['filename'] for a in selected})==len(NAMES)
        target_ids={a['object_id'] for a in selected}
        def protected():
            return [o for o in store.list_objects(None,SCOPE) if not (
                o['object_type']=='SourceArtifact' and o['object_id'] in target_ids or
                o['object_type']=='FactRecord' and o['data'].get('source_artifact_id') in target_ids)]
        before_protected=digest(protected());before=service.workbench(SCOPE)['material_review']['counts']
        files=[]
        for a in selected:
            assert a['status']=='ACTIVE' and a['data']['observed_period']=='2026-01'
            assert a['data']['parse_options']['document_kind']==NAMES[a['data']['filename']]
            old=store.get_object(a['object_id'],SCOPE)
            prior_facts=[store.get_object(fid,SCOPE) for fid in a['data']['parsed_fact_ids']]
            if a['data'].get('parse_version')==PARSER_VERSION:
                result={'artifact':a,'facts':prior_facts,'counts':a['data']['parse_counts']}
            else:
                result=service.execute_command(SCOPE,action='parse_artifact',target_id=a['object_id'],target_version=a['version'],
                    idempotency_key='clarity-'+PARSER_VERSION+'-'+a['object_id'],actor_id='material-clarity-parser-upgrade',
                    role='accountant',payload=a['data']['parse_options'])['effect']
            new=result['artifact'];facts=result['facts']
            assert new['data']['parse_status']!='FAILED'
            assert new['data']['sha256']==old['data']['sha256']
            assert [f['object_id'] for f in facts]==[f['object_id'] for f in prior_facts]
            if NAMES[a['data']['filename']]!='payroll':
                for f,previous in zip(facts,prior_facts):
                    assert all(f['data']['normalized_value'][k]==previous['data']['normalized_value'][k]
                               for k in ('net_amount','tax','invoice_total','invoice_no','invoice_date'))
            else:
                for f,previous in zip(facts,prior_facts):
                    assert all(f['data']['normalized_value'][k]==previous['data']['normalized_value'][k]
                               for k in ('person_name','basic_salary','actual_salary','period'))
            files.append({'filename':a['data']['filename'],'before_version':old['version'],'after_version':new['version'],
                          'counts':result['counts'],'parser_version':new['data']['parse_version']})
        overview=service.workbench(SCOPE);after=overview['material_review']['counts']
        assert before['records']==after['records'] and before['files']==after['files']
        assert after['source_verified']<=before['source_verified']
        assert after['accounting_usable']==before['accounting_usable']==0
        assert digest(protected())==before_protected,'Unrelated originals, historical decisions or financial objects changed'
        assert manifest(target/'artifacts')==originals
        report={'mode':'retained' if retained else 'isolated','status':'PASS','database':str(target/'finwise.db'),
                'backup':str(backup) if backup else None,'before':before,'after':after,'files':files,
                'protected_hash':before_protected,'originals_hash':digest(originals),
                'human_verifications_submitted':0,'model_calls':0,'timestamp':utcnow()}
    out=ROOT/'output/material-clarity';out.mkdir(parents=True,exist_ok=True)
    (out/('retained.json' if retained else 'isolated.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply-retained',action='store_true')
    run(parser.parse_args().apply_retained)
