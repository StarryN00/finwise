from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.ontology.gateway import AgentGateway, DeepSeekProvider, GatewayFailure, GatewayResult
from app.ontology.contracts import Scope
from app.ontology.errors import GatewayPaused
from test_system import build_demo


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


def settings_for(tmp_path, **overrides):
    values = {
        "root": tmp_path,
        "database_path": tmp_path / "finwise.db",
        "storage_path": tmp_path / "artifacts",
        "require_auth": True,
        "environment": "staging",
        "agent_mode": "gateway",
        "agent_provider": "deepseek",
        "agent_model": "deepseek-chat",
        "deepseek_base_url": "https://api.deepseek.com",
        "deepseek_api_key": "secret-test-key",
        "agent_prompt_version": "prompt-test-v1",
        "agent_max_tokens": 512,
        "gateway_timeout_seconds": 5.0,
        "gateway_max_retries": 0,
    }
    values.update(overrides)
    return Settings(**values)


def test_deepseek_provider_parses_json_and_records_real_metadata(tmp_path):
    settings = settings_for(tmp_path)
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["authorization"] = request.headers["Authorization"]
        seen["timeout"] = timeout
        return FakeResponse({
            "id": "chatcmpl-test",
            "choices": [{"message": {"content": json.dumps({
                "status": "PROPOSED", "summary": "候选", "confidence": 0.8,
                "items": [], "evidence": ["evidence-1"], "risk_level": "LOW", "next_action": "人工确认",
            }, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        })

    result = DeepSeekProvider(settings, opener=opener).complete(stage="RULE_SUGGESTION", request_payload={"evidence": ["evidence-1"]}, input_hash="in-hash")
    assert result.mock is False
    assert result.model_version == "deepseek-chat"
    assert result.output["status"] == "PROPOSED"
    assert result.usage["completion_tokens"] == 20
    assert seen["url"].endswith("/chat/completions")
    assert seen["authorization"] == "Bearer secret-test-key"
    assert seen["body"]["temperature"] == 0


def test_deepseek_provider_rejects_non_json_agent_content(tmp_path):
    settings = settings_for(tmp_path)

    def opener(request, timeout):
        return FakeResponse({"choices": [{"message": {"content": "not-json"}}]})

    with pytest.raises(GatewayFailure, match="不是合法 JSON"):
        DeepSeekProvider(settings, opener=opener).complete(stage="EXCEPTION", request_payload={}, input_hash="x")


def test_payroll_mapping_has_own_prompt_schema_and_no_amount_generation(tmp_path):
    from test_payroll_mapping import proposal
    seen={}
    def opener(request,timeout):
        seen.update(json.loads(request.data.decode()))
        return FakeResponse({'choices':[{'message':{'content':json.dumps(proposal())}}],'usage':{'total_tokens':5}})
    r=DeepSeekProvider(settings_for(tmp_path),opener=opener).complete(stage='PAYROLL_MAPPING',request_payload={'sanitized_input':{}},input_hash='structure')
    assert r.metadata()['schema_version']=='payroll-mapping-v1'
    assert r.prompt_version=='payroll-mapping-prompt-v1'
    assert r.mock is False and seen['max_tokens']>=4096
    assert '不输出任何金额' in seen['messages'][0]['content']
    assert 'slips' in seen['messages'][0]['content']
    assert json.loads(seen['messages'][1]['content'])['schema_version']=='payroll-mapping-v1'


def test_gateway_retry_only_retries_transient_provider_failures(tmp_path):
    settings = settings_for(tmp_path, gateway_max_retries=1)
    calls = {"count": 0}

    class FlakyProvider:
        def complete(self, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise GatewayFailure("temporarily unavailable", "PROVIDER_UNAVAILABLE")
            return GatewayResult({"status": "PROPOSED"}, "deepseek", "deepseek-chat", False, "p", "i", "o", 1, {})

    result = AgentGateway(settings, provider=FlakyProvider()).complete(
        Scope(tenant_id="t", organization_id="o", legal_entity_id="l", ledger_id="b", accounting_period_id="2026-03", baseline_id="base"),
        stage="EXCEPTION", sanitized_input={},
    )
    assert result.mock is False
    assert calls["count"] == 2


def test_runtime_gateway_requires_secret_and_auth(tmp_path):
    with pytest.raises(ValueError, match="必须配置 FINWISE_DEEPSEEK_API_KEY"):
        settings_for(tmp_path, deepseek_api_key="").validate_runtime()
    with pytest.raises(ValueError, match="必须开启认证"):
        settings_for(tmp_path, require_auth=False).validate_runtime()


def test_service_persists_real_gateway_metadata_and_keeps_candidate_only(client, scope):
    demo = build_demo(client, scope)
    service = client.app.state.service

    class FakeGateway:
        configured_model = "deepseek-chat"

        def complete(self, scope, *, stage, sanitized_input):
            return GatewayResult(
                output={
                    "status": "PROPOSED", "summary": "真实 Gateway 候选", "confidence": 0.82,
                    "items": [{"debit_account": "库存商品"}],
                    "evidence": demo["group"]["data"]["evidence_ids"],
                    "risk_level": "LOW", "next_action": "人工确认",
                },
                provider="deepseek", model_version="deepseek-chat", mock=False,
                prompt_version="prompt-test-v1", input_hash="input-hash", output_hash="output-hash",
                latency_ms=12, usage={"total_tokens": 42}, request_id="chatcmpl-test",
            )

    service.gateway = FakeGateway()
    result = service.agent_suggest_rule(Scope.model_validate(scope), group_id=demo["group"]["object_id"], actor_id="staging-operator", model_output=None)
    assert result["model_run"]["data"]["gateway"]["mock"] is False
    assert result["model_run"]["data"]["gateway"]["provider"] == "deepseek"
    assert result["candidate"]["status"] == "PROPOSED"
    assert service.store.list_objects("RuleInstance", Scope.model_validate(scope)) == []


def test_invalid_real_gateway_output_is_paused_as_mock_false(client, scope):
    demo = build_demo(client, scope)
    service = client.app.state.service

    class InvalidGateway:
        configured_model = "deepseek-chat"

        def complete(self, scope, *, stage, sanitized_input):
            return GatewayResult({"status": "NOT_PROPOSED"}, "deepseek", "deepseek-chat", False, "p", "i", "o", 3, {})

    service.gateway = InvalidGateway()
    with pytest.raises(GatewayPaused):
        service.agent_suggest_rule(Scope.model_validate(scope), group_id=demo["group"]["object_id"], actor_id="staging-operator", model_output=None)
    paused = service.store.list_objects("ModelRun", Scope.model_validate(scope), statuses=["PAUSED"])[-1]
    assert paused["data"]["gateway"]["mock"] is False
