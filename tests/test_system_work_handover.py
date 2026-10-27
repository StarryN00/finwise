"""系统消化不动的事项要带着结论交给人。

交接说明 §7 把这件列为"当前最挡路的一件"：复核判成 SYSTEM_REVIEW /
INSUFFICIENT / BUSINESS_REVIEW 之后，事项仍然归系统、停在「等待系统检查」。
两个后果：`_progress_with_digestion` 会让「AI 处理」那一步永远完不成
（它按 handling.owner == 'SYSTEM' 判断系统还没消化完），而人在待办里
根本看不到这件事，也不知道系统已经查过什么。
"""
import pytest

from app.material_guidance import MaterialGuidance
from app.ontology.service import _progress_with_digestion


def task(status=None, message=None, **extra):
    """一件归系统分流的事项，可带一个复核结论。"""
    item = {'triage': {'route': 'SYSTEM', 'next_action': '该事项先由系统检查。'}, **extra}
    if status:
        item['problem_review'] = {'status': status,
                                  'data': {'result': {'message': message} if message else {}}}
    return item


def handling(*args, **kwargs):
    return MaterialGuidance._handling(task(*args, **kwargs), True)


@pytest.mark.parametrize('status,label', [
    ('SYSTEM_REVIEW', '系统读取存疑，待你核对识别结果'),
    ('BUSINESS_REVIEW', '待你做业务判断'),
    ('INSUFFICIENT', '系统证据不足，待你核对依据'),
])
def test_a_concluded_review_hands_the_item_to_a_person(status, label):
    """三种结论都是"系统做完了、自己解决不了"，只是下一步谁来做不一样。"""
    result = handling(status)

    assert result['owner'] == 'USER'
    assert result['state'] == 'NEEDS_DECISION'
    assert result['label'] == label
    assert result['action_label'] == '选择处理方式', '要人做事就得给得出动作'


def test_the_review_conclusion_travels_with_the_item():
    """带着结论交给人 —— 不是只把归属翻过来。

    复核那句话是服务端按本地证据生成的，不是模型原话，比模板具体。
    """
    result = handling('SYSTEM_REVIEW', '销售方税号与票面不一致，识别结果需要核对。')

    assert result['explanation'] == '销售方税号与票面不一致，识别结果需要核对。'


def test_an_overlong_conclusion_falls_back_to_the_short_one():
    """和建议卡同一条规则（≤80 字直接用）。

    复核的 message 会把多条检查结论拼起来，可能很长。卡片上要的是一句
    说得清的话；完整结论在折叠的复核详情里一直看得到。
    """
    result = handling('INSUFFICIENT', '依据不足。' * 30)

    assert len(result['explanation']) <= 80
    assert result['explanation'] == '系统查过但证据不足以自己下结论，请核对它列出的依据。'


def test_a_missing_conclusion_still_says_what_to_do():
    assert handling('BUSINESS_REVIEW')['explanation'].startswith('原件里本来就没有这个信息')


def test_system_review_never_tells_the_operator_to_go_ask_the_client():
    """SYSTEM_REVIEW 是系统怀疑自己读错了。

    复核自己的结论里写明"不能据此要求客户补材料" —— 交给人时这条边界
    不能丢，否则会计会把系统的读取问题当成客户少给了材料。
    """
    assert '不要据此要求客户补材料' in handling('SYSTEM_REVIEW')['explanation']


@pytest.mark.parametrize('status,label', [
    ('QUEUED', '等待系统复核'), ('RUNNING', '系统正在复核'), ('FAILED', '系统复核失败'),
])
def test_a_review_still_in_flight_stays_with_the_system(status, label):
    result = handling(status)

    assert result['owner'] == 'SYSTEM'
    assert result['label'] == label


def test_an_item_the_system_has_not_looked_at_yet_stays_with_the_system():
    """还没复核的确实是"等待系统检查"，这一条没有变。"""
    result = handling()

    assert result['owner'] == 'SYSTEM'
    assert result['label'] == '等待系统检查'
    assert result['explanation'] == '该事项先由系统检查。'


def test_handing_the_item_over_lets_the_ai_step_finish():
    """这是交接说明点名的后果：事项归系统，「AI 处理」就永远完不成。"""
    stages = [{'id': 'source', 'name': '导入当月资料', 'status': 'COMPLETED', 'summary': '已接收'},
              {'id': 'analysis', 'name': 'AI 处理', 'status': 'COMPLETED', 'summary': '已形成 63 条结构化事实'},
              {'id': 'confirmation', 'name': '人工确认', 'status': 'WAITING', 'summary': '等待'}]
    progress = {'stages': stages, 'completed_count': 2, 'overall_percent': 66,
                'current_stage': 'confirmation'}
    concluded = {'id': '1', 'deferred': False, 'handling': handling('INSUFFICIENT')}

    result = _progress_with_digestion(progress, {'tasks': [concluded]})

    analysis = next(s for s in result['stages'] if s['id'] == 'analysis')
    assert analysis['status'] == 'COMPLETED', '结论已经出来了，这一步就该算完成'
    assert result['current_stage'] == 'confirmation', '人该在第 5 步看到这件事'


def test_an_item_the_system_is_still_chewing_does_hold_the_ai_step_open():
    """反过来也要成立，否则就是把门禁整个拆了。"""
    stages = [{'id': 'analysis', 'name': 'AI 处理', 'status': 'COMPLETED', 'summary': '已形成'},
              {'id': 'confirmation', 'name': '人工确认', 'status': 'WAITING', 'summary': '等待'}]
    progress = {'stages': stages, 'completed_count': 1, 'overall_percent': 50,
                'current_stage': 'confirmation'}
    running = {'id': '1', 'deferred': False, 'handling': handling('RUNNING')}

    result = _progress_with_digestion(progress, {'tasks': [running]})

    assert next(s for s in result['stages'] if s['id'] == 'analysis')['status'] == 'PARTIAL'
    assert '还有 1 项系统尚未消化完' in next(
        s for s in result['stages'] if s['id'] == 'analysis')['summary']
