"""Collect actual call accounting and retained-data invariants, read-only on DBs."""
import json
from pathlib import Path
from activate_problem_review import objects
from reparse_january_materials import manifest

root=Path(__file__).resolve().parents[1]
out=root/'output/guidance-cards'
isolated=json.loads((out/'isolated.json').read_text())
retained=json.loads((out/'retained.json').read_text())
backup=Path(retained['backup']);original=objects(backup/'finwise.db')
current=objects(root/'data/staging-juxianda-2026-01-from-2025/finwise.db')
assert all(current.get(k)==v for k,v in original.items())
assert manifest(backup/'artifacts')==manifest(root/'data/staging-juxianda-2026-01-from-2025/artifacts')
calls=[]
for environment,db in [('isolated',Path(isolated['isolated_path'])/'finwise.db'),
                       ('staging',root/'data/staging-juxianda-2026-01-from-2025/finwise.db')]:
    for key,obj in objects(db).items():
        if key in original or obj['object_type']!='ModelRun':continue
        data=json.loads(obj['data_json']);metadata=data.get('gateway',{})
        if data.get('stage')=='MATERIAL_GUIDANCE' and metadata.get('mock') is False:
            calls.append({'environment':environment,'id':key,'status':obj['status'],'metadata':metadata})
report={'preserved':True,'calls':calls,'model_calls':len(calls),
        'total_tokens':sum(c['metadata'].get('usage',{}).get('total_tokens',0) for c in calls),
        'fee':'Provider response does not include a charged amount; no price estimate substituted.',
        'per_environment':{e:sum(c['environment']==e for c in calls) for e in ('isolated','staging')},
        'backup':str(backup),'pid':retained['pid']}
(out/'delivery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:report[k] for k in ('preserved','model_calls','total_tokens','per_environment')},ensure_ascii=False))
