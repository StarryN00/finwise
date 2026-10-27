from pathlib import Path
import pytest

from app.ontology.contracts import Scope
from app.ontology.errors import PreconditionFailed
from app.stage23_bridge import Stage23PilotService, attach_delivery
from app.stage23_pilot import sha256, write_json
from test_monthly_agent import validation_fixture


def prepare(client, scope, tmp_path):
    sc = Scope(**scope)
    service = Stage23PilotService(client.app.state.store)
    client.app.state.service = service
    service.create_scope(sc)
    folder = tmp_path/'run'
    workspace = folder/'executor'
    review = folder/'review-1'
    d, tables = validation_fixture()
    d['entries'][0]['name'] = '银行存款'
    d['entries'][1]['name'] = '实收资本'
    d['voucher_assessments'] = [{'voucher': '记-001', 'status': 'READY_FOR_REVIEW',
        'reason': '原件支持候选处理', 'evidence': [{'source_id': 'journal', 'sheet': 'Sheet', 'row': 1}], 'finding_ids': []}]
    sources=[]
    for sid in tables:
        path=workspace/'sources'/f'{sid}.txt';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(sid)
        sources.append({'id':sid,'filename':path.name,'path':str(path.relative_to(workspace)),'sha256':sha256(path)})
    write_json(workspace/'manifest.json', {'period':sc.accounting_period_id,'sources':sources})
    write_json(workspace/'work/delivery.json', d)
    write_json(review/'candidate/delivery.json', d)
    write_json(review/'candidate/mechanical.json', {'passed':True})
    write_json(review/'review.json', {'verdict':'pass','defects':[], 'coverage':[{'area':'测试依据'}], 'ready_vouchers':['记-001']})
    write_json(folder/'frozen.json', {s['path']:s['sha256'] for s in sources})
    write_json(folder/'status.json', {'status':'ANALYSIS_ACCEPTED','delivery_sha256':sha256(workspace/'work/delivery.json'),'review_dir':'review-1'})
    return service, sc, folder


def test_native_review_only_after_acceptance_and_source_integrity(client,scope,tmp_path):
    service,sc,folder=prepare(client,scope,tmp_path)
    packet=attach_delivery(service,sc,folder)
    assert attach_delivery(service,sc,folder)['object_id']==packet['object_id']
    vouchers=service.store.list_objects('VoucherVersion',sc)
    assert len(vouchers)==1 and vouchers[0]['status']=='DRAFT'
    next_step=service.workbench(sc)['material_review']['next_step']
    assert next_step['version']=='workbench-next-step-v1'
    assert next_step['action']['kind']=='VOUCHERS'
    assert not service.store.list_objects('DeliveryPackage',sc)
    assert service.store.get_object(service._baseline_object_id(sc),sc)['status']=='DRAFT'
    v=vouchers[0]
    command={'scope':scope,'action':'validate_draft','target_id':v['object_id'],'target_version':1,
             'idempotency_key':'stage23-review-test','payload':{}}
    denied=client.post('/api/v1/commands',json=command,headers={'X-Role':'viewer'})
    assert denied.status_code==403
    reply=client.post('/api/v1/commands',json=command)
    assert reply.status_code==200,reply.text
    latest=service.store.get_object(v['object_id'],sc)
    assert latest['status']=='LOCALLY_CONFIRMED' and not latest['data']['formal_balance_impact']
    assert not service.store.list_objects('DeliveryPackage',sc)


def test_source_change_blocks_review(client,scope,tmp_path):
    service,sc,folder=prepare(client,scope,tmp_path)
    packet=attach_delivery(service,sc,folder)
    ref=packet['data']['source_versions'][0]
    source=service.store.get_object(ref['id'],sc)
    service.store.revise_object(source['object_id'],source['version'],sc,source['data'],status='ARCHIVED',created_by='test')
    with pytest.raises(PreconditionFailed,match='版本或状态变化'):
        service.validate_draft(sc,voucher_id=packet['data']['vouchers'][0],actor_id='test',expected_version=1)


def test_normal_service_rejects_pilot_and_review_mismatch(client,scope,tmp_path):
    service,sc,folder=prepare(client,scope,tmp_path)
    service.stage23_pilot_enabled=False
    with pytest.raises(PreconditionFailed,match='隔离环境'):
        attach_delivery(service,sc,folder)
    service.stage23_pilot_enabled=True
    write_json(folder/'review-1/review.json',{'verdict':'pass','defects':[],'coverage':[{}],'ready_vouchers':[]})
    with pytest.raises(PreconditionFailed,match='范围不一致'):
        attach_delivery(service,sc,folder)
    assert not service.store.list_objects('VoucherVersion',sc)
