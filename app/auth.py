"""Server-owned identities, revocable sessions and exact-scope grants.

Legacy actor headers are accepted only in explicitly unauthenticated test mode.
No default password, implicit administrator or wildcard scope is provisioned.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError

from app.db import Database, utcnow
from app.ontology.contracts import Scope
from app.ontology.errors import PermissionDenied, ScopeViolation
from app.ontology.store import scope_key

COOKIE = "finwise_session"
SESSION_TTL = 8 * 60 * 60
ROLES = {"operator", "accountant", "reviewer", "admin", "viewer"}
router = APIRouter(prefix="/api/v1/auth")


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()
    return salt + ":" + value


def create_user(database: Database, user_id: str, password: str, role: str) -> None:
    if role not in ROLES or not user_id.strip() or len(password) < 12:
        raise ValueError("用户名、角色必须有效，密码至少 12 个字符")
    with database.connect() as connection:
        connection.execute("INSERT INTO auth_users(user_id,password_hash,role,created_at) VALUES (?,?,?,?)",
                           (user_id, password_hash(password), role, utcnow()))


def grant_scope(database: Database, user_id: str, scope: Scope) -> None:
    with database.connect() as connection:
        connection.execute("INSERT OR IGNORE INTO auth_scope_grants(user_id,scope_json) VALUES (?,?)",
                           (user_id, scope_key(scope)))


def authorized_scopes(request: Request) -> list[Scope]:
    """Return only scopes visible to the current server-owned identity."""
    principal = identity(request)
    if principal.get("test_mode"):
        objects = request.app.state.store.list_scope_objects()
        return [Scope.model_validate(item["data"]["scope"]) for item in objects]
    with request.app.state.database.connect() as connection:
        rows = connection.execute(
            "SELECT scope_json FROM auth_scope_grants WHERE user_id=? ORDER BY scope_json",
            (principal["user_id"],),
        ).fetchall()
    return [Scope.model_validate(json.loads(row["scope_json"])) for row in rows]


def identity(request: Request) -> dict[str, Any]:
    if hasattr(request.state, "identity"):
        return request.state.identity
    if not request.app.state.settings.require_auth:
        principal = {"user_id": request.headers.get("x-actor-id", "operator-demo"),
                     "role": request.headers.get("x-role", "operator").lower(), "test_mode": True}
    else:
        token = request.cookies.get(COOKIE, "")
        if not token:
            raise HTTPException(401, "请先登录")
        with request.app.state.database.connect() as connection:
            row = connection.execute(
                """SELECT s.*,u.role FROM auth_sessions s JOIN auth_users u ON u.user_id=s.user_id
                   WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1""",
                (hashlib.sha256(token.encode()).hexdigest(), int(time.time())),
            ).fetchone()
        if row is None:
            raise HTTPException(401, "登录已失效，请重新登录")
        principal = dict(row)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not hmac.compare_digest(
            request.headers.get("x-csrf-token", ""), principal["csrf_token"]
        ):
            raise HTTPException(403, "请求校验失败，请刷新页面后重试")
    request.state.identity = principal
    return principal


def authorize_scope(request: Request, scope: Scope) -> dict[str, Any]:
    principal = identity(request)
    if principal.get("test_mode"):
        return principal
    with request.app.state.database.connect() as connection:
        granted = connection.execute("SELECT 1 FROM auth_scope_grants WHERE user_id=? AND scope_json=?",
                                     (principal["user_id"], scope_key(scope))).fetchone()
    if not granted:
        request.app.state.store.add_audit("ACCESS_REJECTED", principal["user_id"], scope,
                                         reason="操作人没有该企业、账套、期间和基线的授权")
        raise ScopeViolation("无权访问该处理范围")
    return principal


async def authorize_api(request: Request) -> None:
    path = request.url.path.removeprefix("/api/v1")
    if path in {"/health", "/ontology/contract"}:
        return
    principal = identity(request)
    if path == "/portfolio":
        return
    if request.method == "GET":
        raw_scope = dict(request.query_params)
    else:
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise HTTPException(422, "请求必须为合法 JSON")
        if not isinstance(body, dict):
            raise HTTPException(422, "请求必须为对象")
        raw_scope = body if path == "/scopes" else body.get("scope")
    try:
        scope = Scope.model_validate(raw_scope)
    except ValidationError:
        raise HTTPException(422, "必须提供完整且有效的 Scope")
    authorize_scope(request, scope)
    read_only = path in {"/workbench", "/query", "/objects/detail", "/history", "/baseline/candidate"} or request.method == "GET"
    if read_only:
        return
    if principal["role"] not in ROLES - {"viewer"}:
        raise PermissionDenied("当前角色只可查看，不能写入")
    if path != "/commands":
        request.app.state.service._ensure_period_open(scope)
    if not principal.get("test_mode") and (path.startswith("/demo/") or path.endswith("/complete") or (path == "/commands" and body.get("action") == "complete_run")):
        raise PermissionDenied("演示数据及 Worker 完成回调不对业务用户开放")
    if not principal.get("test_mode") and path.startswith("/agent/"):
        # Real model transport is server-owned; fixture output is never a production input.
        if "model_output" in body:
            raise PermissionDenied("业务接口不接受客户端伪造的模型输出")


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response) -> dict[str, Any]:
    database = request.app.state.database
    now = int(time.time())
    # No forwarded IP headers are trusted; unknown users receive the same failure and hash work.
    attempt_key = hashlib.sha256((body.username + "|" + (request.client.host if request.client else "unknown")).encode()).hexdigest()
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        attempt = connection.execute("SELECT * FROM auth_login_attempts WHERE attempt_key=?", (attempt_key,)).fetchone()
        failures = attempt["failures"] if attempt and now - attempt["window_started"] < 300 else 0
        started = attempt["window_started"] if failures else now
        if failures >= 5:
            raise HTTPException(429, "登录尝试过于频繁，请稍后重试")
        row = connection.execute("SELECT * FROM auth_users WHERE user_id=? AND enabled=1", (body.username,)).fetchone()
        encoded = row["password_hash"] if row else "00" * 16 + ":" + "00" * 32
        valid = hmac.compare_digest(password_hash(body.password, encoded.split(":")[0]), encoded) and row is not None
        if not valid:
            connection.execute("INSERT OR REPLACE INTO auth_login_attempts VALUES (?,?,?)", (attempt_key, failures + 1, started))
            connection.commit()
            raise HTTPException(401, "用户名或密码不正确")
        connection.execute("DELETE FROM auth_login_attempts WHERE attempt_key=?", (attempt_key,))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        connection.execute("DELETE FROM auth_sessions WHERE expires_at<=?", (now,))
        connection.execute("INSERT INTO auth_sessions VALUES (?,?,?,?)",
                           (hashlib.sha256(token.encode()).hexdigest(), row["user_id"], csrf, now + SESSION_TTL))
        old_token = request.cookies.get(COOKIE)
        if old_token:
            connection.execute("DELETE FROM auth_sessions WHERE token_hash=?", (hashlib.sha256(old_token.encode()).hexdigest(),))
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https", max_age=SESSION_TTL)
    response.headers["Cache-Control"] = "no-store"
    return {"user_id": row["user_id"], "role": row["role"], "csrf_token": csrf}


@router.get("/me")
def me(request: Request, response: Response) -> dict[str, Any]:
    principal = identity(request)
    response.headers["Cache-Control"] = "no-store"
    return {key: principal.get(key) for key in ("user_id", "role", "csrf_token")}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    principal = identity(request)
    with request.app.state.database.connect() as connection:
        connection.execute("DELETE FROM auth_sessions WHERE token_hash=?", (principal.get("token_hash", ""),))
    response.delete_cookie(COOKIE)
    return {"logged_out": True}
