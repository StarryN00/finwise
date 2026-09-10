from copy import deepcopy

import pytest

from app.action_types import FALLBACK_IDS
from app.ontology.contracts import Scope
from conftest import command
from test_material_review import setup, view


def unknown_task(client, scope, reason='custom_code：未知业务事项'):
    artifact, facts = setup(client, scope)
    service = client.app.state.service
    typed = Scope(**scope)
    fact = service.store.get_object(facts[0]['object_id'], typed)
    data = deepcopy(fact['data'])
    data['normalized_value']['custom_code'] = 'A'
    data['field_sources']['custom_code'] = {
        'source_label': '自定义业务标记', 'original_value': 'A',
        'region': data['source_anchor']['region'],
    }
    data['extraction_issues'] = [reason]
    current = service.store.revise_object(
        fact['object_id'], fact['version'], typed, data,
        status='NEEDS_REVIEW', created_by='fixture',
    )
    overview = view(client, scope)
    expected = reason.partition('：')[2]
    task = next(item for item in overview['material_review']['tasks'] if item['reason'].endswith(expected))
    return artifact, current, task, overview


@pytest.mark.parametrize('reason', [
    'custom_code：未知合同口径', 'custom_code：未知票据场景', 'custom_code：未知税务事实',
    'custom_code：未知结算关系', 'custom_code：未知期间例外',
])
def test_five_unknown_kinds_enter_human_queue_with_same_catalog_actions(client, scope, reason):
    _, _, task, _ = unknown_task(client, scope, reason)
    fallback = [item for item in task['descriptor']['options'] if item['fallback']]
    assert task['triage']['route'] == 'HUMAN'
    assert task['triage']['matched_rule'] == 'SAFE_UNKNOWN'
    assert [item['id'] for item in fallback] == list(FALLBACK_IDS)
    assert all(effect['grants_accounting_usable'] is False
               for item in fallback for effect in item['effects'])


def execute(client, scope, artifact, task, action_id, values, key, role='accountant'):
    return command(client, scope, 'execute_task_action', artifact['object_id'], artifact['version'], key, {
        'task_id': task['id'], 'descriptor_hash': task['descriptor']['fingerprint'],
        'action_type_id': action_id, 'values': values,
    }, role=role)


def test_record_judgement_is_idempotent_revocable_and_read_only_for_finance(client, scope):
    artifact, fact, task, before = unknown_task(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    originals = {
        'artifact': service.store.get_object(artifact['object_id'], typed),
        'fact': service.store.get_object(fact['object_id'], typed),
        'groups': service.store.list_objects('ProcessingGroup', typed),
        'vouchers': service.store.list_objects('VoucherVersion', typed),
        'period': service.store.list_objects('AccountingPeriod', typed),
    }
    response = execute(client, scope, artifact, task, 'record_judgement', {
        'judgement': '当前事项应先保留为特殊合同判断',
        'reason': '已核对合同条款第 3 条与原始业务标记',
    }, 'task-action-judgement')
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['next']['version'] == 'workbench-next-step-v1'
    decision = body['effect']['object']
    assert decision['object_type'] == 'Decision' and decision['status'] == 'CONFIRMED'
    assert decision['data']['grants_accounting_usable'] is False
    replay = execute(client, scope, artifact, task, 'record_judgement', {
        'judgement': '当前事项应先保留为特殊合同判断',
        'reason': '已核对合同条款第 3 条与原始业务标记',
    }, 'task-action-judgement')
    assert replay.status_code == 200 and replay.json()['idempotent'] is True
    assert replay.json()['next']['version'] == 'workbench-next-step-v1'
    after = view(client, scope)
    projected = next(item for item in after['material_review']['tasks'] if item['id'] == task['id'])
    assert projected['handling']['owner'] == 'SYSTEM'
    assert projected['task_action']['valid'] is True
    assert projected['reason'] == task['reason']
    metrics = after['material_review']['action_metrics']
    assert metrics['executed_action_count'] >= 2
    assert metrics['fallback_action_count'] == 1
    assert metrics['items'] and all(item['drilldown'] for item in metrics['items'])
    assert service.store.get_object(artifact['object_id'], typed) == originals['artifact']
    assert service.store.get_object(fact['object_id'], typed) == originals['fact']
    assert service.store.list_objects('ProcessingGroup', typed) == originals['groups']
    assert service.store.list_objects('VoucherVersion', typed) == originals['vouchers']
    assert service.store.list_objects('AccountingPeriod', typed) == originals['period']
    events = service.store.list_audits(typed, decision['object_id'])
    assert {'TASK_ACTION_EXECUTED', 'ACTION_TYPE_CANDIDATE_REQUESTED'} <= {item['event_type'] for item in events}
    revoked = command(client, scope, 'revoke_task_action', decision['object_id'], decision['version'],
                      'task-action-revoke', {'reason': '取得新合同依据，重新办理'})
    assert revoked.status_code == 200 and revoked.json()['effect']['object']['status'] == 'REVOKED'
    restored = next(item for item in view(client, scope)['material_review']['tasks'] if item['id'] == task['id'])
    assert restored['handling']['owner'] == 'USER'


@pytest.mark.parametrize('role,allowed', [('operator', True), ('accountant', True), ('admin', True), ('viewer', False)])
def test_mark_out_of_scope_permissions_and_effect_boundary(client, scope, role, allowed):
    artifact, fact, task, _ = unknown_task(client, scope)
    response = execute(client, scope, artifact, task, 'mark_out_of_scope', {
        'reason': '该记录属于下一期间的独立合同事项，本期不办理',
    }, 'out-of-scope-' + role, role=role)
    assert response.status_code == (200 if allowed else 403), response.text
    if allowed:
        row = next(item for item in view(client, scope)['material_review']['records']
                   if item['object_id'] == fact['object_id'])
        assert row['period_disposition'] == 'OUT_OF_SCOPE' and row['eligible'] is False


def test_supplement_requires_specific_material_and_fact_and_stale_requests_fail(client, scope):
    artifact, _, task, _ = unknown_task(client, scope)
    vague = execute(client, scope, artifact, task, 'request_supplement', {
        'material': '资料', 'fact_to_verify': '待确认',
    }, 'supplement-vague')
    assert vague.status_code == 409
    stale = command(client, scope, 'execute_task_action', artifact['object_id'], artifact['version'],
                    'supplement-stale', {
                        'task_id': task['id'], 'descriptor_hash': '0' * 64,
                        'action_type_id': 'request_supplement', 'values': {
                            'material': '2026 年 3 月银行回单',
                            'fact_to_verify': '核验该笔付款的实际收款方',
                        },
                    })
    assert stale.status_code == 409
    good = execute(client, scope, artifact, task, 'request_supplement', {
        'material': '2026 年 3 月银行回单',
        'fact_to_verify': '核验该笔付款的实际收款方',
    }, 'supplement-specific')
    assert good.status_code == 200
    projected = next(item for item in view(client, scope)['material_review']['tasks'] if item['id'] == task['id'])
    assert projected['handling']['owner'] == 'EXTERNAL'


def test_escalation_permissions_stop_at_admin(client, scope):
    artifact, _, task, _ = unknown_task(client, scope)
    values = {'reason': '特殊合同事项需要更高权限复核'}
    denied = execute(client, scope, artifact, task, 'escalate', values,
                     'escalate-admin', role='admin')
    assert denied.status_code == 403
    allowed = execute(client, scope, artifact, task, 'escalate', values,
                      'escalate-operator', role='operator')
    assert allowed.status_code == 200
    assert allowed.json()['effect']['object']['data']['escalated_to_role'] == 'accountant'


def test_out_of_scope_rejected_after_formal_downstream_started(client, scope):
    artifact, fact, task, _ = unknown_task(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    service.store.create_initial_object('ProcessingGroup', typed, {
        'stable_identity': 'fixture-formal', 'member_fact_ids': [fact['object_id']],
    }, status='CANDIDATE', created_by='fixture', object_id='fixture-formal-group')
    response = execute(client, scope, artifact, task, 'mark_out_of_scope', {
        'reason': '尝试排除已进入下游的记录',
    }, 'out-of-scope-downstream')
    assert response.status_code == 409
    assert not service.store.list_objects('Decision', typed)


@pytest.mark.parametrize(('action_id', 'values'), [
    ('record_judgement', {
        'judgement': '保留为特殊业务判断',
        'reason': '已核对当前合同条款和原件标记',
    }),
    ('suspend', {'reason': '等待已约定的内部业务复核会议'}),
    ('request_supplement', {
        'material': '2026 年 3 月银行回单',
        'fact_to_verify': '核验该笔付款的实际收款方',
    }),
    ('mark_out_of_scope', {'reason': '该记录属于下期独立合同事项'}),
    ('escalate', {'reason': '涉及特殊合同条款，需管理员复核'}),
])
def test_every_fallback_only_creates_controlled_decision(client, scope, action_id, values):
    artifact, _, task, _ = unknown_task(client, scope, reason=f'custom_code：{action_id} 边界测试')
    service, typed = client.app.state.service, Scope(**scope)
    before = {
        object_type: deepcopy(service.store.list_objects(object_type, typed))
        for object_type in ('SourceArtifact', 'BusinessFact', 'ProcessingGroup',
                            'VoucherVersion', 'AccountingPeriod')
    }
    response = execute(client, scope, artifact, task, action_id, values,
                       f'fallback-read-only-{action_id}', role='accountant')
    assert response.status_code == 200, response.text
    decision = response.json()['effect']['object']
    assert decision['object_type'] == 'Decision'
    assert decision['data']['action_type_id'] == action_id
    assert decision['data']['grants_accounting_usable'] is False
    assert decision['data']['effects']
    assert all(effect['grants_accounting_usable'] is False
               for effect in decision['data']['effects'])
    after = {
        object_type: service.store.list_objects(object_type, typed)
        for object_type in before
    }
    assert after == before
