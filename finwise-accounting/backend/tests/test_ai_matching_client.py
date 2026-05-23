from app.services.ai_matching_service import AiMatchingUnavailableError, MoonshotAiMatchingClient


def test_moonshot_ai_matching_client_converts_timeout_to_domain_error(monkeypatch):
    def fake_urlopen(_request, timeout):
        assert timeout == 45
        raise TimeoutError("timed out")

    monkeypatch.setattr("app.services.ai_matching_service.request.urlopen", fake_urlopen)
    client = MoonshotAiMatchingClient(api_key="test-key", base_url="https://example.test", model="kimi")

    try:
        client.propose_matches({"bank_transactions": [], "invoices": []})
    except AiMatchingUnavailableError as exc:
        assert "AI 服务响应超时" in str(exc)
    else:
        raise AssertionError("expected AiMatchingUnavailableError")
