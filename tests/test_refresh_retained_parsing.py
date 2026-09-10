import sys
from copy import deepcopy
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from refresh_retained_parsing import inventory, inventory_token, apply_checked
from app.ontology.contracts import Scope
from test_tabular_ingestion import uploaded, parse, xlsx_fixture, INVOICE_HEADERS


def old_source(client,scope):
    a=uploaded(client,scope,xlsx_fixture([('发票',[INVOICE_HEADERS,['I-1','2026-03-01','100','13','13%','甲']])]))
    result=parse(client,scope,a).json()['effect'];a=result['artifact'];f=result['facts'][0]
    s=client.app.state.service;typed=Scope(**scope)
    d=deepcopy(a['data']);d['parse_version']='tabular-v2'
    a=s.store.revise_object(a['object_id'],a['version'],typed,d,status='ACTIVE',created_by='old-fixture')
    d=deepcopy(f['data']);d['source_artifact_version']=a['version']
    d['field_sources']={k:{'region':v.get('region'),'row':v.get('row')} for k,v in d['field_sources'].items()}
    s.store.revise_object(f['object_id'],f['version'],typed,d,status=f['status'],created_by='old-fixture')
    return s,typed,a


def database_dump(service):
    with service.store.database.connect() as connection:
        return list(connection.iterdump())


def test_only_stale_result_updates_and_second_run_is_noop(client,scope):
    s,typed,a=old_source(client,scope)
    items=inventory(s,typed);assert len(items)==1 and items[0]['update']
    effects,before,after=apply_checked(s,typed,inventory_token(s,items))
    assert len(effects)==1 and effects[0]['before_count']==effects[0]['after_count']==1
    assert s.store.get_object(a['object_id'],typed)['version']==a['version']+1
    assert before['material_review']['counts']['accounting_usable']==after['material_review']['counts']['accounting_usable']==0
    items=inventory(s,typed);assert not items[0]['update']
    before_dump=database_dump(s)
    assert not apply_checked(s,typed,inventory_token(s,items))[0]
    assert database_dump(s)==before_dump


@pytest.mark.parametrize('failure', ['count','exception'])
def test_post_update_failure_rolls_back_facts_commands_and_audit(client,scope,monkeypatch,failure):
    s,typed,a=old_source(client,scope);items=inventory(s,typed);token=inventory_token(s,items)
    original=s.workbench;calls=[]
    def workbench(scope):
        calls.append(1);view=original(scope)
        if len(calls)==2:
            if failure=='exception':raise RuntimeError('post-update view failed')
            view['material_review']['counts']['accounting_usable']+=1
        return view
    before=database_dump(s)
    monkeypatch.setattr(s,'workbench',workbench)
    with pytest.raises((AssertionError,RuntimeError)):
        apply_checked(s,typed,token)
    assert len(calls)==2 and database_dump(s)==before


def test_other_scope_changes_invalidate_token_before_any_write(client,scope):
    s,typed,a=old_source(client,scope);token=inventory_token(s,inventory(s,typed))
    other=Scope(**{**scope,'accounting_period_id':'__bank_registry__'})
    s.store.create_initial_object('BankAccount',other,{'bank_name':'测试银行'},status='CONFIRMED',created_by='test')
    before=database_dump(s)
    with pytest.raises(AssertionError,match='Full snapshot changed'):
        apply_checked(s,typed,token)
    assert database_dump(s)==before


def test_changed_business_values_are_not_auto_corrected(client,scope):
    s,typed,a=old_source(client,scope);f=s.store.get_object(a['data']['parsed_fact_ids'][0],typed)
    d=deepcopy(f['data']);d['normalized_value']['net_amount']='999.00'
    s.store.revise_object(f['object_id'],f['version'],typed,d,status=f['status'],created_by='test')
    before=database_dump(s)
    with pytest.raises(AssertionError,match='Business values would change'):
        inventory(s,typed)
    assert database_dump(s)==before
