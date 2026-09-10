from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import create_user, grant_scope
from app.config import Settings
from app.main import create_app
from app.ontology.contracts import Scope


@pytest.fixture()
def secured(tmp_path, scope):
    app = create_app(Settings(root=Path(__file__).resolve().parents[1], database_path=tmp_path / "auth.db",
                              storage_path=tmp_path / "artifacts", require_auth=True))
    create_user(app.state.database, "reader", "test-only-reader-password", "viewer")
    create_user(app.state.database, "accountant", "test-only-accountant-password", "accountant")
    for user in ("reader", "accountant"):
        grant_scope(app.state.database, user, Scope(**scope))
    app.state.service.create_scope(Scope(**scope))
    return TestClient(app)


def sign_in(client, user="accountant"):
    response = client.post("/api/v1/auth/login", json={"username": user, "password": f"test-only-{user}-password"})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


@pytest.mark.parametrize("path", ["workbench", "query", "objects/detail", "commands", "scopes"])
def test_forged_headers_never_authenticate(secured, scope, path):
    response = secured.post("/api/v1/" + path, headers={"X-Actor-Id": "admin", "X-Role": "admin"}, json={"scope": scope})
    assert response.status_code == 401


def test_read_write_scope_and_role_are_owned_by_server(secured, scope):
    signed = sign_in(secured, "reader")
    assert "HttpOnly" in signed.headers["set-cookie"] and "SameSite=strict" in signed.headers["set-cookie"]
    assert secured.post("/api/v1/workbench", json={"scope": scope}).status_code == 200
    for field in scope:
        other = {**scope, field: scope[field] + "-other"}
        response = secured.post("/api/v1/workbench", json={"scope": other})
        assert response.status_code == 403, response.text
        assert "objects" not in response.json()
    # A valid session does not make client-supplied roles trustworthy.
    forged = secured.post("/api/v1/scopes", headers={"X-Role": "admin"}, json=scope)
    assert forged.status_code == 403
    file_query = "&".join(f"{k}={v}" for k, v in {**scope, "legal_entity_id": "other"}.items())
    assert secured.get("/api/v1/artifacts/unknown/content?" + file_query).status_code == 403


def test_portfolio_lists_only_server_granted_scopes(secured, scope):
    other = {**scope, "legal_entity_id": "legal-b", "ledger_id": "ledger-b", "baseline_id": "baseline-b-2026-03"}
    secured.app.state.service.create_scope(Scope(**other))
    sign_in(secured, "reader")
    response = secured.get("/api/v1/portfolio")
    assert response.status_code == 200, response.text
    assert response.json()["scope_count"] == 1
    assert response.json()["scopes"][0]["scope"] == scope


def test_cross_page_session_can_restore_csrf_for_portfolio_read_workflows(secured, scope):
    sign_in(secured)
    portfolio = secured.get("/api/v1/portfolio")
    assert portfolio.status_code == 200

    # A new static page has the session cookie but not the in-memory CSRF token.
    secured.headers.pop("X-CSRF-Token", None)
    session = secured.get("/api/v1/auth/me")
    assert session.status_code == 200
    secured.headers["X-CSRF-Token"] = session.json()["csrf_token"]

    assert secured.post("/api/v1/workbench", json={"scope": scope}).status_code == 200
    assert secured.post("/api/v1/history", json={"scope": scope}).status_code == 200


def test_sessions_csrf_expiry_revocation_and_disabled_user(secured, scope):
    sign_in(secured)
    assert secured.get("/api/v1/auth/me").json()["role"] == "accountant"
    response = secured.post("/api/v1/scopes", headers={"X-CSRF-Token": "forged"}, json=scope)
    assert response.status_code == 403
    assert secured.post("/api/v1/scopes", json=scope).status_code == 200
    token = secured.cookies.get("finwise_session")
    assert secured.post("/api/v1/auth/logout").status_code == 200
    secured.cookies.set("finwise_session", token)
    assert secured.get("/api/v1/auth/me").status_code == 401
    sign_in(secured)
    with secured.app.state.database.connect() as con:
        con.execute("UPDATE auth_sessions SET expires_at=0")
    assert secured.get("/api/v1/auth/me").status_code == 401
    sign_in(secured)
    with secured.app.state.database.connect() as con:
        con.execute("UPDATE auth_users SET enabled=0 WHERE user_id='accountant'")
    assert secured.get("/api/v1/auth/me").status_code == 401


def test_demo_and_forged_worker_results_are_not_business_endpoints(secured, scope):
    sign_in(secured)
    for path, payload in [("demo/procurement", {}), ("runs/unknown/complete", {"result": {"mock": False}}),
                          ("commands", {"action": "complete_run"}),
                          ("agent/suggestion", {"model_output": {"status": "PROPOSED"}})]:
        assert secured.post("/api/v1/" + path, json={"scope": scope, **payload}).status_code == 403


def test_login_throttles_and_secrets_are_not_stored_plaintext(secured):
    for _ in range(5):
        assert secured.post("/api/v1/auth/login", json={"username": "reader", "password": "wrong"}).status_code == 401
    assert secured.post("/api/v1/auth/login", json={"username": "reader", "password": "wrong"}).status_code == 429
    with secured.app.state.database.connect() as con:
        assert "test-only" not in con.execute("SELECT password_hash FROM auth_users LIMIT 1").fetchone()[0]
    assert "database" not in secured.get("/api/v1/health").json()


def test_non_artifact_and_unsafe_storage_cannot_be_downloaded(secured, scope):
    from urllib.parse import urlencode
    from app.ontology.contracts import ArtifactInput
    import base64
    sign_in(secured)
    service = secured.app.state.service
    typed = Scope(**scope)
    baseline = service.workbench(typed)["baseline"]
    url = "/api/v1/artifacts/" + baseline["object_id"] + "/content?" + urlencode(scope)
    # Even trusted-server corrupted metadata cannot turn a baseline into a file handle.
    service.store.revise_object(baseline["object_id"], baseline["version"], typed,
                               {"storage_path": str(secured.app.state.settings.database_path)}, status="DRAFT", created_by="test")
    assert secured.get(url).status_code == 404
    artifact = service.create_artifact(ArtifactInput(scope=typed, filename="测试\"文件.txt", content_base64=base64.b64encode(b"original").decode()), actor_id="test")
    url = "/api/v1/artifacts/" + artifact["object_id"] + "/content?" + urlencode(scope)
    response = secured.get(url)
    assert response.content == b"original"
    assert "%22" in response.headers["content-disposition"]
    service.store.revise_object(artifact["object_id"], artifact["version"], typed,
                               {**artifact["data"], "storage_path": str(secured.app.state.settings.database_path)}, status="ACTIVE", created_by="test")
    assert secured.get(url).status_code == 409


def test_deferred_app_initializes_only_on_lifespan(tmp_path):
    path = tmp_path / "not-yet-created" / "database.db"
    app = create_app(Settings(root=Path(__file__).resolve().parents[1], database_path=path,
                              storage_path=tmp_path / "artifacts"), initialize=False)
    assert not path.exists()
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert path.exists()


def test_validation_errors_do_not_echo_passwords(secured):
    secret = "private-password-not-for-response" * 40
    response = secured.post("/api/v1/auth/login", json={"username": "reader", "password": secret})
    assert response.status_code == 422
    assert "private-password" not in response.text
