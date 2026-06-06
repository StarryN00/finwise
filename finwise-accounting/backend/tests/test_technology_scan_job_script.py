from scripts.run_technology_scan_job import classify_interruption_reason, safe_log_message


def test_classify_interruption_reason_maps_provider_interruptions():
    assert classify_interruption_reason("页面出现 captcha 验证") == "CAPTCHA_REQUIRED"
    assert classify_interruption_reason("login required, please sign in") == "LOGIN_REQUIRED"
    assert classify_interruption_reason("搜索结果 ambiguous，存在多家重名企业") == "AMBIGUOUS_MATCH"
    assert classify_interruption_reason("没有找到科创分入口") == "NO_INNOVATION_PANEL"
    assert classify_interruption_reason("请求过快 rate limit") == "PROVIDER_RATE_LIMITED"
    assert classify_interruption_reason("别的异常") == "UNKNOWN_ERROR"


def test_safe_log_message_masks_sensitive_tokens():
    message = safe_log_message("password=abc123 cookie=session token=secret 原始HTML<html>")

    assert "abc123" not in message
    assert "session" not in message
    assert "secret" not in message
    assert "<html>" not in message
