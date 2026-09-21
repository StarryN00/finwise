"""操作人面对的只有四种形态；右侧那四栏就是它们。"""
from app.materials import PROBLEM_KINDS, SYSTEM_KIND, problem_buckets, problem_kind


def task(kind, action='supplement', records=1, deferred=False, problem=None, verified=False):
    rows = [{'object_id': f'r{i}', 'arithmetic_verified': verified} for i in range(records)]
    return {'id': f'{kind}-{action}-{records}-{verified}', 'kind': kind, 'deferred': deferred,
            'record_ids': [r['object_id'] for r in rows],
            'problem_kind': problem or problem_kind(kind, action, rows)}


def test_every_shape_has_a_distinct_thing_for_the_operator_to_do():
    assert set(PROBLEM_KINDS) == {'UNREADABLE', 'UNVERIFIED', 'JUDGEMENT', 'VERIFIED'}
    assert problem_kind('VERIFY', 'verify', [{'arithmetic_verified': True}]) == 'VERIFIED'
    assert problem_kind('VERIFY', 'verify', [{'arithmetic_verified': False}]) == 'UNVERIFIED'
    assert problem_kind('PARSE', 'parse', []) == 'UNREADABLE'
    assert problem_kind('ISSUE', 'supplement', [{}]) == 'JUDGEMENT'


def test_one_unverified_record_drags_the_whole_check_out_of_self_consistent():
    """整份原件是一条事项，所以只要有一条没验过，这份就不算自洽。"""
    rows = [{'arithmetic_verified': True}] * 5 + [{'arithmetic_verified': False}]
    assert problem_kind('VERIFY', 'verify', rows) == 'UNVERIFIED'


def test_buckets_are_in_handling_order_and_self_consistent_needs_nobody():
    buckets = problem_buckets([task('PARSE', 'parse', records=0), task('ISSUE'),
                               task('VERIFY', 'verify', records=3, verified=True)])
    assert [b['kind'] for b in buckets] == ['UNREADABLE', 'UNVERIFIED', 'JUDGEMENT', 'VERIFIED']
    assert [b['count'] for b in buckets] == [1, 0, 1, 1]
    assert [b['needs_user'] for b in buckets] == [True, True, True, False]
    assert buckets[-1]['record_count'] == 3


def test_system_maintenance_is_not_shown_as_a_problem_for_the_operator():
    """解析规则升级后重读一遍是系统自己该做完的事，不是给人的问题。"""
    buckets = problem_buckets([task('PARSE', 'parse', records=0, problem=SYSTEM_KIND)])
    assert all(b['count'] == 0 for b in buckets)


def test_deferred_items_leave_the_buckets_but_are_not_deleted():
    buckets = problem_buckets([task('ISSUE', deferred=True)])
    assert all(b['count'] == 0 for b in buckets)
