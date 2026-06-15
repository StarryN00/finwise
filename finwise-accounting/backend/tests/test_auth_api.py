import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


PASSWORD_HASH = "pbkdf2_sha256$260000$dGVzdC1zYWx0$XufFqtDz8CSHTvfTCBbWmcdMaSWynTvFI8PjelT6Gvo"


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("FINWISE_AUTH_ENABLED", "true")
    monkeypatch.setenv("FINWISE_ADMIN_USERNAME", "operator")
    monkeypatch.setenv("FINWISE_ADMIN_PASSWORD_HASH", PASSWORD_HASH)
    monkeypatch.setenv("FINWISE_JWT_SECRET", "test-secret")
    monkeypatch.setenv("FINWISE_TOKEN_EXPIRE_HOURS", "1")
    get_settings.cache_clear()
    return TestClient(create_app(init_db_on_startup=False), raise_server_exceptions=False)


def login_as_operator(client: TestClient, password: str = "secret-pass") -> str:
    resp = client.post("/api/auth/login", json={"username": "operator", "password": password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_auth_protects_api_but_keeps_health_public(monkeypatch):
    client = make_client(monkeypatch)

    assert client.get("/health").status_code == 200
    assert client.get("/api/auth/status").json() == {"enabled": True}
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/workspace").status_code == 401


def test_login_issues_bearer_token_and_me_accepts_it(monkeypatch):
    client = make_client(monkeypatch)

    bad = client.post("/api/auth/login", json={"username": "operator", "password": "wrong"})
    assert bad.status_code == 401

    resp = client.post("/api/auth/login", json={"username": "operator", "password": "secret-pass"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["username"] == "operator"

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "operator"


def test_change_password_persists_hash_and_requires_new_login(monkeypatch, tmp_path):
    password_file = tmp_path / "auth" / "admin.hash"
    monkeypatch.setenv("FINWISE_PASSWORD_HASH_FILE", str(password_file))
    client = make_client(monkeypatch)
    token = login_as_operator(client)

    changed = client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"old_password": "secret-pass", "new_password": "new-secret-pass"},
    )

    assert changed.status_code == 200
    assert changed.json() == {"ok": True}
    assert password_file.exists()
    assert "new-secret-pass" not in password_file.read_text()
    assert client.post("/api/auth/login", json={"username": "operator", "password": "secret-pass"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "operator", "password": "new-secret-pass"}).status_code == 200


def test_change_password_rejects_wrong_current_password(monkeypatch, tmp_path):
    password_file = tmp_path / "auth" / "admin.hash"
    monkeypatch.setenv("FINWISE_PASSWORD_HASH_FILE", str(password_file))
    client = make_client(monkeypatch)
    token = login_as_operator(client)

    resp = client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"old_password": "wrong", "new_password": "new-secret-pass"},
    )

    assert resp.status_code == 401
    assert not password_file.exists()


def test_docs_are_disabled_when_auth_is_enabled(monkeypatch):
    client = make_client(monkeypatch)

    assert client.get("/docs").status_code == 404
