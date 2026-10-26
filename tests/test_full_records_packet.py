"""全量模式：整条记录交给模型，不再只发字段名。

脱敏包里模型看不到任何业务内容，所以不管什么问题，它能给的都是"缺字段，去要材料"
—— 实测 20 条建议几乎全落在同一个选项上。要它就具体业务给建议，就得让它看见业务。
这会把客户财务数据发给外部服务商，所以默认关闭，由部署方明确打开。
"""
from app.config import Settings
from app.material_guidance import full_packet, safe_packet


def task():
    return {
        'kind': 'ISSUE', 'filename': '荣鼎坤8月进项.xlsx',
        'reason': '业务期间：开票日期不在税款所属期内',
        'title': '业务期间待核对',
        'triage': {'route': 'HUMAN'},
        'descriptor': {
            'title': '确认费用归属期间',
            'why': {'facts': '1 条记录', 'rule': '开票日期须落在税款所属期内',
                    'recommendation': '请确认归属期间'},
            'scope': {'accounting_period_id': '2026-08'},
            'options': [{'id': 'supplement', 'label': '补充资料（可选）', 'available': True,
                         'completion': '已补充', 'not_effects': ['不改原件']},
                        {'id': 'defer_material_issue', 'label': '暂无法补充', 'available': True,
                         'completion': '已记录', 'not_effects': []}],
        },
    }


def record():
    return {
        'object_id': 'r1', 'record_type': 'INVOICE', 'state': 'PERIOD_EXCEPTION',
        'values': {'invoice_no': '26352000001880551996', 'counterparty': '昆山某某机械',
                   'summary': '采购钢材', 'invoice_total': '156.00', 'invoice_date': '2026-07-30'},
        'issues': ['业务期间：开票日期 2026-07-30 不在税款所属期 2026-08 内'],
        'comparison': [{'field': 'invoice_date', 'state': 'DIRECT_MATCH',
                        'source_value': '2026-07-30', 'value': '2026-07-30', 'region': '发票!H4'}],
    }


def test_the_model_can_see_the_business_when_full_records_are_on():
    packet = full_packet(task(), [record()])
    row = packet['records'][0]
    assert row['values']['counterparty'] == '昆山某某机械'
    assert row['values']['summary'] == '采购钢材'
    assert row['issues'][0].startswith('业务期间')
    assert row['comparison'][0]['source_value'] == '2026-07-30'
    assert packet['task']['filename'] == '荣鼎坤8月进项.xlsx'
    assert packet['task']['period'] == '2026-08'


def test_the_desensitised_packet_still_shows_nothing_of_the_business():
    packet = safe_packet(task(), [record()])
    text = repr(packet)
    for secret in ('昆山某某机械', '采购钢材', '26352000001880551996', '156.00'):
        assert secret not in text, secret


def test_full_mode_uses_the_real_option_labels_not_fixed_meanings():
    """脱敏包里选项标签换成了服务端写死的固定说法，模型看不到真实的动作名称。"""
    assert [o['label'] for o in full_packet(task(), [record()])['options']] == ['补充资料（可选）', '暂无法补充']
    assert [o['label'] for o in safe_packet(task(), [record()])['options']] != ['补充资料（可选）', '暂无法补充']


def test_system_routed_items_still_offer_no_options_in_either_mode():
    """先由系统检查的事项不该让模型替人挑动作。"""
    routed = {**task(), 'triage': {'route': 'SYSTEM'}}
    assert full_packet(routed, [record()])['options'] == []
    assert safe_packet(routed, [record()])['options'] == []


def test_full_mode_is_off_unless_the_deployment_turns_it_on():
    assert Settings.__dataclass_fields__['agent_send_full_records'].default is False


def test_the_boundary_still_travels_with_the_full_packet():
    """看得见业务不等于可以替人决定。"""
    limit = full_packet(task(), [record()])['context_limit']
    assert '只能从 options 里选' in limit and '不能替用户确认' in limit


def settings(**overrides):
    from pathlib import Path
    import dataclasses
    base = Settings(root=Path('.'), database_path=Path('x.db'), storage_path=Path('a'),
                    agent_max_tokens=4000, agent_reasoning_max_tokens=8000,
                    gateway_timeout_seconds=45.0, gateway_reasoning_timeout_seconds=180.0)
    return dataclasses.replace(base, **overrides)


def test_full_records_need_a_bigger_answer_budget_on_every_tier():
    """看到整条业务记录后模型答得更具体也更长 ——
    实测建议档在 4000 下有一多半以 finish_reason=length 截断。"""
    off, on = settings(), settings(agent_send_full_records=True)
    assert off.tokens_for('MATERIAL_GUIDANCE') == 4000
    assert on.tokens_for('MATERIAL_GUIDANCE') == 8000
    assert on.tokens_for('PROBLEM_REVIEW') == 8000


def test_full_records_also_need_the_longer_wait():
    assert settings().timeout_for('MATERIAL_GUIDANCE') == 45.0
    assert settings(agent_send_full_records=True).timeout_for('MATERIAL_GUIDANCE') == 180.0


def test_the_vision_tier_keeps_its_own_much_larger_budget():
    """扫描件要逐行抄录，额度本来就比推理档高，不能被压下来。"""
    on = settings(agent_send_full_records=True, agent_vision_max_tokens=16000)
    assert on.tokens_for('SCANNED_DOCUMENT') == 16000
