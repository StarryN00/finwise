"""第二步没消化完，就不该显示成已完成。"""
from app.ontology.service import _progress_with_digestion


def progress(analysis='COMPLETED'):
    stages = [{'id': 'source', 'name': '资料接收', 'status': 'COMPLETED', 'summary': '已接收'},
              {'id': 'analysis', 'name': '资料分析', 'status': analysis, 'summary': '已形成 63 条结构化事实'},
              {'id': 'validation', 'name': '待确认与校验', 'status': 'WAITING', 'summary': '等待'}]
    return {'stages': stages, 'completed_count': sum(s['status'] == 'COMPLETED' for s in stages),
            'overall_percent': 66, 'current_stage': 'analysis'}


def tasks(*owners, deferred=False):
    return {'tasks': [{'id': str(i), 'deferred': deferred, 'handling': {'owner': o}}
                      for i, o in enumerate(owners)]}


def test_analysis_stays_open_while_the_system_is_still_digesting():
    """否则界面上「资料分析 ✓」会和第三步里一堆「等待系统检查」同时成立。"""
    result = _progress_with_digestion(progress(), tasks('SYSTEM', 'SYSTEM', 'USER'))
    analysis = next(s for s in result['stages'] if s['id'] == 'analysis')
    assert analysis['status'] == 'PARTIAL'
    assert '还有 2 项系统尚未消化完' in analysis['summary']
    assert '已形成 63 条结构化事实' in analysis['summary'], '原本的解析结论不能被覆盖掉'
    assert result['completed_count'] == 1 and result['current_stage'] == 'analysis'


def test_work_that_belongs_to_a_person_does_not_hold_the_step_open():
    """人要做的事属于第三步；把它算成"系统没消化完"就永远进不去。"""
    result = _progress_with_digestion(progress(), tasks('USER', 'EXTERNAL', 'NONE'))
    assert next(s for s in result['stages'] if s['id'] == 'analysis')['status'] == 'COMPLETED'
    assert result['completed_count'] == 2


def test_deferred_items_are_not_the_system_waiting_on_itself():
    result = _progress_with_digestion(progress(), tasks('SYSTEM', deferred=True))
    assert next(s for s in result['stages'] if s['id'] == 'analysis')['status'] == 'COMPLETED'


def test_an_unfinished_parse_is_not_overwritten_into_looking_finished():
    result = _progress_with_digestion(progress(analysis='PARTIAL'), tasks('SYSTEM'))
    analysis = next(s for s in result['stages'] if s['id'] == 'analysis')
    assert analysis['status'] == 'PARTIAL' and analysis['summary'] == '已形成 63 条结构化事实'
