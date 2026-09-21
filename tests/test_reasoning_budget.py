"""推理档的输出额度必须够写完答案。

实测：PROBLEM_REVIEW 用 deepseek-v4-pro、额度 1200 时，推理就把额度花光，
返回空内容加 finish_reason=length。界面上只显示"分析失败"，
看不出是被截断 —— 这个问题挡了很久。
"""
import json

import pytest

from app.ontology.gateway import DeepSeekProvider, GatewayFailure
from test_parse_plan_integration import FakeResponse, settings_for


def calls(tmp_path, stage, content, finish_reason=None, **overrides):
    seen = {}

    def opener(request, timeout):
        seen.update(json.loads(request.data))
        return FakeResponse({'choices': [{'finish_reason': finish_reason,
                                          'message': {'content': content}}]})
    provider = DeepSeekProvider(settings_for(tmp_path, **overrides), opener=opener)
    return provider, seen


def test_reasoning_stages_get_their_own_budget_not_the_default_1200(tmp_path):
    provider, seen = calls(tmp_path, 'PROBLEM_REVIEW', json.dumps({'ok': True}))
    provider.complete(stage='PROBLEM_REVIEW', request_payload={}, input_hash='t')
    assert seen['max_tokens'] == 8000


def test_light_stages_keep_the_cheap_default(tmp_path):
    provider, seen = calls(tmp_path, 'MATERIAL_GUIDANCE', json.dumps({'ok': True}), agent_max_tokens=1200)
    provider.complete(stage='MATERIAL_GUIDANCE', request_payload={}, input_hash='t')
    assert seen['max_tokens'] == 1200


def test_a_truncated_agent_reply_says_it_was_truncated(tmp_path):
    """只说"不是合法 JSON"会把人引向"模型不会输出 JSON"。"""
    provider, _ = calls(tmp_path, 'PROBLEM_REVIEW', '', finish_reason='length')
    with pytest.raises(GatewayFailure) as error:
        provider.complete(stage='PROBLEM_REVIEW', request_payload={}, input_hash='t')
    assert error.value.code == 'AGENT_INVALID_JSON'
    assert '输出被 max_tokens 截断' in str(error.value)


def test_a_malformed_reply_that_was_not_truncated_says_so_instead(tmp_path):
    provider, _ = calls(tmp_path, 'PROBLEM_REVIEW', '这不是 JSON', finish_reason='stop')
    with pytest.raises(GatewayFailure) as error:
        provider.complete(stage='PROBLEM_REVIEW', request_payload={}, input_hash='t')
    assert 'finish_reason=stop' in str(error.value)
    assert '这不是 JSON' in str(error.value), '内容开头要交出来，否则无从判断模型说了什么'


def test_reasoning_stages_also_get_a_longer_wait(tmp_path):
    """额度给够了但只等 45 秒，失败的表现和模型答不上来一模一样。"""
    waits = []

    def opener(request, timeout):
        waits.append(timeout)
        return FakeResponse({'choices': [{'finish_reason': 'stop',
                                          'message': {'content': json.dumps({'ok': True})}}]})
    provider = DeepSeekProvider(settings_for(tmp_path, gateway_timeout_seconds=45.0), opener=opener)
    provider.complete(stage='PROBLEM_REVIEW', request_payload={}, input_hash='t')
    provider.complete(stage='MATERIAL_GUIDANCE', request_payload={}, input_hash='t')
    assert waits == [180.0, 45.0]
