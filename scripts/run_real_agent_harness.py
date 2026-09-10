#!/usr/bin/env python3
"""Run a redacted, server-authenticated real Agent Gateway smoke test.

This script never accepts or sends model_output.  It is intentionally a
small HTTP client so the same auth/CSRF boundary used by the operator page is
tested in Staging.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Allow direct execution from a checkout without requiring an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings


def parse_bool(value: str) -> bool:
    value = value.lower()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    raise argparse.ArgumentTypeError("布尔值必须是 true 或 false")


def call_json(base_url: str, path: str, payload: dict[str, Any], *, cookie: str = "", csrf: str = "") -> tuple[int, dict[str, Any], str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    if csrf:
        headers["X-CSRF-Token"] = csrf
    request = urllib.request.Request(base_url.rstrip("/") + path, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}, response.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            decoded = {"error": {"message": body[:500]}}
        return exc.code, decoded, exc.headers.get("Set-Cookie", "")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Staging 服务不可用: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="FinWise 真实 Agent Gateway Harness")
    parser.add_argument("--preflight", action="store_true", help="只检查本地配置，不调用模型")
    parser.add_argument("--base-url", default=os.getenv("FINWISE_HARNESS_BASE_URL", "http://127.0.0.1:8766"))
    parser.add_argument("--scope-json", type=Path)
    parser.add_argument("--group-id")
    parser.add_argument("--stage", default="RULE_SUGGESTION")
    parser.add_argument("--username", default=os.getenv("FINWISE_HARNESS_USERNAME", ""))
    parser.add_argument("--password", default=os.getenv("FINWISE_HARNESS_PASSWORD", ""))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--replay", action="store_true", help="成功后通过既有命令接口创建固定输入回放 Run")
    parser.add_argument("--mock", type=parse_bool, default=False, help="仅用于拒绝回归；真实 Harness 必须保持 false")
    args = parser.parse_args()

    settings = Settings.from_env()
    report: dict[str, Any] = {
        "harness": "finwise-real-agent-harness-v1",
        "mock": args.mock,
        "configured": bool(settings.agent_mode == "gateway" and settings.deepseek_api_key),
        "mode": settings.agent_mode,
        "provider": settings.agent_provider,
        "model": settings.agent_model,
    }
    try:
        settings.validate_runtime()
    except ValueError as exc:
        report.update({"status": "BLOCKED", "reason": str(exc)})
        return finish(report, args.report, 2)
    if settings.agent_mode != "gateway":
        report.update({"status": "BLOCKED", "reason": "真实 Harness 要求 FINWISE_AGENT_MODE=gateway"})
        return finish(report, args.report, 2)
    if args.mock:
        report.update({"status": "BLOCKED", "reason": "真实 Harness 禁止使用 --mock=true"})
        return finish(report, args.report, 2)
    if args.preflight:
        report.update({"status": "READY", "reason": "Gateway 配置完整，尚未执行模型调用"})
        return finish(report, args.report, 0)
    if not args.scope_json or not args.group_id or not args.username or not args.password:
        report.update({"status": "BLOCKED", "reason": "真实调用需要 --scope-json、--group-id、Staging 用户名和密码"})
        return finish(report, args.report, 2)
    try:
        scope = json.loads(args.scope_json.read_text(encoding="utf-8"))
        if not isinstance(scope, dict):
            raise ValueError("Scope JSON 必须是对象")
        status, login, set_cookie = call_json(args.base_url, "/api/v1/auth/login", {"username": args.username, "password": args.password})
        if status != 200:
            report.update({"status": "FAILED", "reason": "Staging 登录失败", "http_status": status})
            return finish(report, args.report, 1)
        cookie = set_cookie.split(";", 1)[0]
        csrf = login.get("csrf_token", "")
        body = {"scope": scope, "stage": args.stage, "group_id": args.group_id}
        status, response, _ = call_json(args.base_url, "/api/v1/agent/suggestion", body, cookie=cookie, csrf=csrf)
        run_id = response.get("model_run", {}).get("data", {}).get("run_id")
        report.update({"status": "PASSED" if status == 200 else "FAILED", "http_status": status,
                       "run_id": run_id,
                       "gateway": response.get("model_run", {}).get("data", {}).get("gateway", {}),
                       "error": response.get("error")})
        if status == 200 and args.replay and run_id:
            replay_key = "harness-replay:" + run_id
            replay_status, replay_response, _ = call_json(
                args.base_url, "/api/v1/commands",
                {"action": "replay_run", "target_id": run_id, "target_version": 1,
                 "scope": scope, "idempotency_key": replay_key, "payload": {}},
                cookie=cookie, csrf=csrf,
            )
            report["replay"] = {"status": "PASSED" if replay_status == 200 else "FAILED", "http_status": replay_status,
                                 "run_id": replay_response.get("effect", {}).get("run", {}).get("run_id"),
                                 "error": replay_response.get("error")}
            if replay_status != 200:
                report["status"] = "FAILED"
        return finish(report, args.report, 0 if report["status"] == "PASSED" else 1)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        report.update({"status": "FAILED", "reason": str(exc)})
        return finish(report, args.report, 1)


def finish(report: dict[str, Any], path: Path | None, code: int) -> int:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return code


if __name__ == "__main__":
    sys.exit(main())
