"""Start browser acceptance against the already-tested disposable copy only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.db import Database
from app.auth import grant_scope
from app.ontology.store import ObjectStore
from app.ontology.service import OntologyService
from app.ontology.contracts import Scope
from import_juxianda_january import SCOPE

root=Path(__file__).resolve().parents[1]
report=json.loads((root/'output/guidance-cards/isolated.json').read_text())
dataset=Path(report['isolated_path']).resolve()
assert 'finwise-guidance-cards-' in str(dataset) and dataset.name=='dataset'
import psutil
runtime=psutil.Process(int(sys.argv[1]))
assert Path(runtime.cwd())==root and runtime.cmdline()[-2:]==['--port','8767']
environment=runtime.environ()
environment.update(FINWISE_DATABASE_PATH=str(dataset/'finwise.db'),FINWISE_STORAGE_PATH=str(dataset/'artifacts'))
os.environ.update({k:v for k,v in environment.items() if k.startswith('FINWISE_')})
svc=OntologyService(ObjectStore(Database(Settings.from_env(root))))
target=Scope(**{**SCOPE.model_dump(),'accounting_period_id':'2026-02','baseline_id':'acceptance-february'})
svc.create_scope(target,actor_id='isolated-acceptance')
grant_scope(svc.store.database,'juxianda-staging',target)
fd,log=tempfile.mkstemp(prefix='finwise-guidance-acceptance-',suffix='.log')
with os.fdopen(fd,'wb') as stream:
    process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:create_app','--factory','--host','127.0.0.1','--port','8768','--lifespan','off'],cwd=root,env=environment,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
(root/'output/guidance-cards/browser-server.json').write_text(json.dumps({'pid':process.pid,'log':log,'target_scope':target.model_dump()}))
print(json.dumps({'pid':process.pid,'port':8768,'isolated':str(dataset)}))
