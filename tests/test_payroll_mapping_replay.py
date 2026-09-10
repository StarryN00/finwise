"""Synthetic replay checks; all writes stay in the pytest temporary database."""
from copy import deepcopy

import pytest

from app.ontology.contracts import Scope
from app.ontology.errors import PreconditionFailed, ScopeViolation
from conftest import command
from test_payroll_mapping import request, setup
from test_tabular_ingestion import xlsx_fixture


@pytest.fixture()
def applied(client,app,scope,monkeypatch):
    raw=xlsx_fixture([('工资',[
        ['工资表 所属期 2026-03'],
        ['员工','底薪','实付','公司社保','个人社保'],
        ['合成员工甲',2000,3500.18,400,200],
        ['合成员工乙',2100,3600,450,210],
        ['合计',4100,7100.18,850,410],
    ])])
    artifact,calls=setup(client,app,scope,raw)
    assert request(client,scope,artifact).status_code==200
    service=app.state.service.payroll_mapping
    assert service.run_once()
    bound_scope=Scope(**scope)
    job=app.state.store.list_objects('PayrollMapping',bound_scope)[-1]
    response=command(client,scope,'apply_payroll_mapping',job['object_id'],job['version'],
                     'replay-apply',{'proposal':job['data']['proposal'],'mapping_confirmed':True})
    assert response.status_code==200,response.text
    effect=response.json()['effect']
    assert len(calls)==1

    def forbidden(*args,**kwargs):
        pytest.fail('Replay must not call a model, built-in parser or write objects')

    monkeypatch.setattr(app.state.service.gateway,'complete',forbidden)
    monkeypatch.setattr('app.tabular.extract_workbook',forbidden)
    monkeypatch.setattr(app.state.service,'parse_artifact',forbidden)
    return service,bound_scope,effect


def revise_job(service,scope,job,*,changes=None,status=None):
    return service.store.revise_object(job['object_id'],job['version'],scope,
        {**job['data'],**(changes or {})},status=status or job['status'],created_by='test')


def test_replay_matches_applied_facts_without_writes_or_cached_preview(applied,monkeypatch):
    service,scope,effect=applied
    revise_job(service,scope,effect['object'],changes={'preview':{'records':[]}})
    with service.store.database.connect() as connection:
        before=list(connection.iterdump())
    artifact=deepcopy(effect['artifact'])
    original=deepcopy(artifact)
    extracted=service.replay(scope,artifact)
    assert artifact==original
    assert len(extracted['records'])==2
    for row,fact in zip(extracted['records'],effect['facts']):
        for key in ('source_anchor','normalized_value','original_value','field_sources','period_check','extraction_issues'):
            assert row[key]==fact['data'][key]
        assert row['period_check']=='PASS' and not row['extraction_issues']
    assert extracted['records'][0]['normalized_value']['actual_salary']=='3500.18'
    assert extracted['records'][0]['field_sources']['actual_salary']['region']=='工资!C3'
    assert any('汇总' in row['reason'] for row in extracted['checks']['excluded_rows'])
    with service.store.database.connect() as connection:
        assert list(connection.iterdump())==before


@pytest.mark.parametrize('status',['QUEUED','RUNNING','REVIEW','FAILED','STALE','SUPERSEDED'])
def test_replay_rejects_unapplied_or_invalidated_mapping(applied,status):
    service,scope,effect=applied
    revise_job(service,scope,effect['object'],status=status)
    with pytest.raises(PreconditionFailed,match='绑定已失效'):
        service.replay(scope,effect['artifact'])


@pytest.mark.parametrize('changes',[
    {'artifact_id':'another-artifact'},
    {'applied_artifact_version':1},
    {'applied_artifact_version':None},
    {'sha256':'0'*64},
    {'schema_version':'unknown-version'},
])
def test_replay_rejects_invalid_binding(applied,changes):
    service,scope,effect=applied
    revise_job(service,scope,effect['object'],changes=changes)
    with pytest.raises(PreconditionFailed,match='绑定已失效'):
        service.replay(scope,effect['artifact'])


@pytest.mark.parametrize('proposal',[None,{}, {'sheets':[],'confidence':1}])
def test_replay_rejects_missing_or_invalid_proposal(applied,proposal):
    service,scope,effect=applied
    revise_job(service,scope,effect['object'],changes={'proposal':proposal})
    with pytest.raises(PreconditionFailed,match='方案不能回放'):
        service.replay(scope,effect['artifact'])


def test_replay_validates_proposal_against_source(applied):
    service,scope,effect=applied
    proposal=deepcopy(effect['object']['data']['proposal'])
    proposal['sheets'][0]['fields']['actual_salary']='ZZ'
    revise_job(service,scope,effect['object'],changes={'proposal':proposal})
    with pytest.raises(PreconditionFailed,match='方案不能回放'):
        service.replay(scope,effect['artifact'])


@pytest.mark.parametrize('mapping_id',[None,'missing-mapping','wrong-type'])
def test_replay_rejects_missing_or_wrong_mapping(applied,mapping_id):
    service,scope,effect=applied
    artifact=effect['artifact'];job=effect['object']
    if mapping_id=='wrong-type':
        mapping_id=service.store.create_initial_object('OtherMapping',scope,job['data'],
            status='APPLIED',created_by='test')['object_id']
    artifact=service.store.revise_object(artifact['object_id'],artifact['version'],scope,
        {**artifact['data'],'payroll_mapping_id':mapping_id},status='ACTIVE',created_by='test')
    with pytest.raises(PreconditionFailed):
        service.replay(scope,artifact)


@pytest.mark.parametrize('dimension',list(Scope.model_fields))
def test_replay_rejects_cross_scope_artifact_and_mapping(applied,dimension):
    service,scope,effect=applied
    foreign=scope.model_copy(update={dimension:'foreign-scope'})
    with pytest.raises(PreconditionFailed,match='Scope'):
        service.replay(foreign,effect['artifact'])
    # Even a same-scope artifact cannot borrow an applied mapping from another scope.
    job=service.store.create_initial_object('PayrollMapping',foreign,effect['object']['data'],
        status='APPLIED',created_by='test')
    artifact=effect['artifact']
    artifact=service.store.revise_object(artifact['object_id'],artifact['version'],scope,
        {**artifact['data'],'payroll_mapping_id':job['object_id']},status='ACTIVE',created_by='test')
    with pytest.raises(ScopeViolation):
        service.replay(scope,artifact)


@pytest.mark.parametrize('status',['ACTIVE','ARCHIVED'])
def test_replay_rejects_changed_source_version_or_status(applied,status):
    service,scope,effect=applied
    artifact=effect['artifact']
    current=service.store.revise_object(artifact['object_id'],artifact['version'],scope,
        artifact['data'],status=status,created_by='test')
    for candidate in (artifact,current):
        with pytest.raises(PreconditionFailed):
            service.replay(scope,candidate)


def test_replay_rejects_changed_file_bytes(applied,monkeypatch):
    service,scope,effect=applied
    path=service.store.database.settings.storage_path/effect['artifact']['data']['storage_path']
    original=type(path).read_bytes
    monkeypatch.setattr(type(path),'read_bytes',lambda p: b'changed' if p==path else original(p))
    with pytest.raises(PreconditionFailed,match='哈希'):
        service.replay(scope,effect['artifact'])
