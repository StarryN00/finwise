"""主线六步：这条路是给人看的，所以它的身份和顺序要有东西盯着。

这里只测 `app/main_flow.py` 的装配口径。两条处理路径各自的状态算法分别在
`test_system.py`（传统管线）和 `test_autonomous_workflow.py`（月度自主处理）。
"""
import pytest

from app import main_flow


def stages(**overrides):
    base = {stage_id: {'status': 'COMPLETED', 'summary': stage_id}
            for stage_id in main_flow.MAIN_LINE_IDS}
    base['delivery'] = {'status': 'WAITING', 'summary': '尚未正式交付'}
    for stage_id, value in overrides.items():
        base[stage_id] = {'summary': stage_id, **value}
    return base


def test_the_six_business_steps_are_the_main_line_and_delivery_is_not():
    """进度条上人看到的就是这六步，顺序固定。"""
    flow = main_flow.build(stages())

    assert [item['name'] for item in flow['stages'] if item['main_line']] == [
        '创建企业', '导入历史资料', '导入当月资料', 'AI 处理', '人工确认', '凭证生成与复核']
    assert [item['id'] for item in flow['stages'] if not item['main_line']] == ['delivery']


def test_delivery_never_holds_the_month_back_from_looking_finished():
    """交付归档在当前实现里永远 WAITING。

    算进百分比的话，一个月其实已经做完了也只能显示 83%，看起来总差一步。
    """
    flow = main_flow.build(stages())

    assert flow['total_count'] == 6 and flow['completed_count'] == 6
    assert flow['overall_percent'] == 100
    assert flow['current_stage'] == 'voucher', '六步都完成时指针停在最后一步，不落到主线外'


def test_the_pointer_stops_at_the_first_step_that_still_needs_doing():
    flow = main_flow.build(stages(analysis={'status': 'RUNNING'}, confirmation={'status': 'WAITING'},
                                  voucher={'status': 'WAITING'}))

    assert flow['current_stage'] == 'analysis'
    assert flow['completed_count'] == 3 and flow['overall_percent'] == 50


def test_a_step_that_can_wait_does_not_capture_the_pointer():
    """历史账表正在被系统处理时，人该去整理本期资料，不是盯着第 2 步等。

    prerequisite 自己的说明就是"处理期间可继续整理本期资料"；指针停在第 2 步
    会让人不知道下一步能做什么。
    """
    flow = main_flow.build(stages(history={'status': 'WAITING', 'can_wait': True},
                                  source={'status': 'NOT_STARTED'},
                                  analysis={'status': 'NOT_STARTED'},
                                  confirmation={'status': 'NOT_STARTED'},
                                  voucher={'status': 'NOT_STARTED'}))

    assert flow['current_stage'] == 'source'
    history = next(item for item in flow['stages'] if item['id'] == 'history')
    assert history['status'] == 'WAITING', '不捕获指针不等于算它完成了，这一格仍然没打勾'


def test_a_history_problem_that_needs_a_person_does_capture_the_pointer():
    """要人动手的历史问题不是"可以先放着"。"""
    flow = main_flow.build(stages(history={'status': 'BLOCKED'}, source={'status': 'NOT_STARTED'}))

    assert flow['current_stage'] == 'history'


def test_the_pointer_still_lands_on_a_waiting_step_when_nothing_else_is_open():
    """只剩一个可以先放着的步骤时仍然指它，否则指针会落在已完成的步骤上。"""
    flow = main_flow.build(stages(history={'status': 'WAITING', 'can_wait': True}))

    assert flow['current_stage'] == 'history'


def test_a_missing_main_line_step_is_a_programming_error_not_a_silent_gap():
    """少给一步就该当场报错。

    静默跳过的后果是进度条少一格、百分比的分母悄悄变了，排查起来很贵。
    """
    incomplete = stages()
    del incomplete['confirmation']

    with pytest.raises(KeyError, match='人工确认|confirmation'):
        main_flow.build(incomplete)
