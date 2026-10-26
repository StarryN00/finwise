"""口径只有一处：problem_review 的覆盖层不得自己再算一遍记录与任务计数。

实测过的后果：复核覆盖层把 active_tasks 重新算成「所有未延后的任务」，
把 optional 的抽查任务又算了回去，界面上的待办数怎么改都不动。
"""
import inspect

from app.materials import review_counts
import app.problem_review as problem_review


def records(states, verified=0):
    rows = [{'state': s} for s in states]
    for row in rows[:verified]:
        row['arithmetic_verified'] = True
    return rows


def task(kind='VERIFY', deferred=False, optional=False):
    return {'kind': kind, 'deferred': deferred, 'optional': optional}


def test_optional_checks_leave_the_todo_count_alone():
    counts = review_counts(records(['AWAITING_VERIFICATION'] * 3, verified=3),
                           [task(optional=True), task(kind='ISSUE')])
    assert counts['active_tasks'] == 1
    assert counts['optional_tasks'] == 1
    assert counts['awaiting_verification_active'] == 0


def test_state_counts_stay_true_to_the_records():
    """算术已核对不改记录状态，加总恒等式仍然成立。"""
    counts = review_counts(records(['AWAITING_VERIFICATION', 'AWAITING_VERIFICATION', 'SOURCE_VERIFIED'],
                                   verified=1), [])
    assert counts['awaiting_verification'] == 2
    assert counts['arithmetic_verified'] == 1
    assert counts['system_checked'] == 3


def test_problem_review_overlay_reuses_the_shared_counter():
    source = inspect.getsource(problem_review)
    assert 'review_counts(' in source
    assert "active_tasks=sum(" not in source
    assert "awaiting_verification=states[" not in source
