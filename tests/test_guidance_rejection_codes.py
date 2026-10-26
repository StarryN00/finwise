"""模型答案没过本地校验时，要知道是哪一条校验拦的。

只有笼统的 GUIDANCE_REJECTED 时，分不清是选项不在闭集里、引用编造还是步骤不合法，
排查只能靠猜。校验项的名字是服务端自己定义的，不是模型内容，留痕不泄露任何原文。
"""
import pytest

from app.material_guidance import CandidateRejected, validate_candidates


def packet(options=('supplement',), records=('record-1',)):
    return {'options': [{'id': o} for o in options],
            'records': [{'reference': r} for r in records]}


def candidate(**overrides):
    base = {'option_id': 'supplement', 'reason': '缺银行账户，建议请对方补材料。',
            'uncertainties': [], 'prefill': {}, 'confidence': 0.9,
            'evidence_refs': ['record-1'], 'steps': []}
    return {'candidates': [{**base, **overrides}]}


def test_a_good_answer_passes():
    assert validate_candidates(candidate(), {}, packet())[0]['option_id'] == 'supplement'


@pytest.mark.parametrize('overrides,code', [
    ({'option_id': '自己发明的动作'}, 'OPTION_NOT_IN_CLOSED_SET'),
    ({'evidence_refs': ['record-99']}, 'INVALID_EVIDENCE_REFS'),
    ({'evidence_refs': ['record-1', 'record-1']}, 'INVALID_EVIDENCE_REFS'),
    ({'prefill': {'date': '2026-08-01'}}, 'INVALID_CANDIDATE_FIELDS'),
    ({'option_id': None, 'steps': [{'option_id': 'supplement', 'instruction': '去补材料'}]},
     'STEPS_WITHOUT_OPTION'),
])
def test_each_guard_says_which_one_it_was(overrides, code):
    with pytest.raises(CandidateRejected) as error:
        validate_candidates(candidate(**overrides), {}, packet())
    assert error.value.code == code


def test_a_duplicate_option_is_named_too():
    value = candidate()
    value['candidates'] = value['candidates'] * 2
    with pytest.raises(CandidateRejected) as error:
        validate_candidates(value, {}, packet())
    assert error.value.code == 'DUPLICATE_OPTION'


def test_the_code_carries_no_model_text():
    """留痕的是校验项名字，不能把模型原文捎带出去。"""
    with pytest.raises(CandidateRejected) as error:
        validate_candidates(candidate(option_id='自己发明的动作'), {}, packet())
    assert '自己发明的动作' not in str(error.value)
