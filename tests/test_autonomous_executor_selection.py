from dataclasses import replace
import json
from fastapi.testclient import TestClient
import pytest

from app.ontology.contracts import Scope
from app.ontology.errors import PreconditionFailed
from test_autonomous_workflow import setup


def enable_claude(workflow):
    workflow.settings=replace(workflow.settings,autonomous_claude_path='/usr/bin/true')


def test_switch_preserves_old_result_and_pins_next_loop(setup):
    app,service,scope,source,mature,result=setup
    w=service.autonomous;enable_claude(w);mature();assert w.tick(scope)
    before=w.current(scope);old_voucher=w.project(scope)['vouchers'][0]
    original=service.store.get_object(source['object_id'],scope)
    client=TestClient(app)
    response=client.post('/api/v1/autonomous/executor',json={'scope':scope.model_dump(),'backend':'claude_code'})
    assert response.status_code==200,response.text
    job=w.current(scope)
    assert job['data']['runtime']['backend']=='claude_code'
    assert job['data']['parent_id']==before['object_id']
    assert service.store.get_object(before['object_id'],scope)['status']=='ACCEPTED'
    assert not w.project(scope)['vouchers']
    with pytest.raises(PreconditionFailed):
        service.validate_draft(scope,voucher_id=old_voucher['object_id'],actor_id='alice',expected_version=1)
    with pytest.raises(PreconditionFailed):
        w.answer(scope,'alice','operator',before['object_id'],'old-finding','旧页面回答')
    seen=[]
    def runner(*args):
        seen.append((args[4].autonomous_backend,args[4].autonomous_claude_model));return result()
    w.runner=runner
    w.settings=replace(w.settings,autonomous_claude_model='opus')
    mature();assert w.tick(scope)
    assert seen==[('claude_code','sonnet')]
    assert w.project(scope)['vouchers'][0]['status']=='DRAFT'
    assert service.store.get_object(source['object_id'],scope)==original
    assert w.select_backend(scope,'alice','operator','claude_code')['object_id']==job['object_id']
    assert 'Claude Code' in json.dumps(w.project(scope)['autonomous_workflow']['history'])


def test_switch_requires_pause_valid_backend_and_permission(setup):
    app,service,scope,*_=setup;w=service.autonomous;enable_claude(w)
    client=TestClient(app);payload={'scope':scope.model_dump(),'backend':'claude_code'}
    assert client.post('/api/v1/autonomous/executor',json=payload,headers={'X-Role':'viewer'}).status_code==403
    response=client.post('/api/v1/autonomous/executor',json=payload)
    assert response.status_code==409 and '先暂停' in response.text
    assert client.post('/api/v1/autonomous/executor',json={**payload,'backend':'arbitrary-command'}).status_code==422
    assert client.post('/api/v1/autonomous/executor',json={**payload,'path':'/tmp/other'}).status_code==422
    w.cancel(scope,'alice','operator')
    assert client.post('/api/v1/autonomous/executor',json=payload).status_code==200


def test_preupload_choice_and_unavailable_backend(setup):
    _,service,scope,*_=setup;w=service.autonomous;enable_claude(w)
    empty=Scope(**{**scope.model_dump(),'legal_entity_id':'empty-company','baseline_id':'empty-baseline'})
    service.create_scope(empty)
    assert w.select_backend(empty,'alice','operator','claude_code') is None
    assert w.project(empty)['autonomous_workflow']['executor']=='claude_code'
    assert not w.current(empty)
    w.settings=replace(w.settings,autonomous_claude_path='/nonexistent/claude')
    with pytest.raises(PreconditionFailed,match='路径无效'):
        w.select_backend(empty,'alice','operator','claude_code')


def test_legacy_run_remains_codex_when_server_default_changes(setup):
    _, service, scope, _, mature, _ = setup
    w = service.autonomous
    enable_claude(w)
    mature()
    assert w.tick(scope)
    old = w.current(scope)
    watch = w.watch(scope)
    legacy = {key: value for key, value in watch['data'].items() if key != 'backend'}
    service.store.revise_object(watch['object_id'], watch['version'], scope, legacy, status='ACTIVE', created_by='alice')
    w.settings = replace(w.settings, autonomous_backend='claude_code')
    assert w.selected_backend(scope) == 'codex'
    new = w.select_backend(scope, 'alice', 'operator', 'claude_code')
    assert new['object_id'] != old['object_id']
    assert new['data']['runtime']['backend'] == 'claude_code'
