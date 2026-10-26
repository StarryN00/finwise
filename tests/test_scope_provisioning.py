"""开设处理范围：界面上能新建企业，但不能借此拿到别人已有的数据。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import create_user, grant_scope
from app.config import Settings
from app.main import create_app
from app.ontology.contracts import Scope

HEADERS = {"X-Actor-Id": "alice", "X-Role": "accountant"}


def new_scope(entity="昆山荣鼎坤机械科技有限公司", period="2026-06"):
    return {"tenant_id": "昆山某代账", "organization_id": "昆山某代账",
            "legal_entity_id": entity, "ledger_id": "主账套",
            "accounting_period_id": period, "baseline_id": f"{entity}-{period}"}


def test_provision_creates_the_scope_and_makes_it_visible(client, scope):
    response = client.post("/api/v1/scopes/provision", headers=HEADERS, json=new_scope())
    assert response.status_code == 200, response.text
    assert response.json()["scope"]["data"]["scope"]["legal_entity_id"] == "昆山荣鼎坤机械科技有限公司"
    listing = client.get("/api/v1/portfolio", headers=HEADERS).json()
    entities = {item["scope"]["legal_entity_id"] for item in listing.get("scopes", listing.get("items", []))}
    assert "昆山荣鼎坤机械科技有限公司" in entities


def test_provision_refuses_an_existing_scope(client, scope):
    assert client.post("/api/v1/scopes/provision", headers=HEADERS, json=new_scope()).status_code == 200
    again = client.post("/api/v1/scopes/provision", headers=HEADERS, json=new_scope())
    assert again.status_code == 409
    assert "已存在" in again.text


def test_readonly_role_cannot_provision(client, scope):
    response = client.post("/api/v1/scopes/provision",
                           headers={"X-Actor-Id": "bob", "X-Role": "viewer"}, json=new_scope())
    assert response.status_code == 403


def test_provision_is_recorded_in_the_audit_trail(client, scope):
    client.post("/api/v1/scopes/provision", headers=HEADERS, json=new_scope())
    audits = client.app.state.service.store.list_audits(Scope(**new_scope()))
    assert [a["event_type"] for a in audits if a["event_type"] == "SCOPE_PROVISIONED"] == ["SCOPE_PROVISIONED"]


def test_provision_rejects_an_incomplete_scope(client, scope):
    body = new_scope()
    body.pop("baseline_id")
    assert client.post("/api/v1/scopes/provision", headers=HEADERS, json=body).status_code == 422


@pytest.fixture()
def secured(tmp_path: Path):
    settings = Settings(root=Path(__file__).resolve().parents[1],
                        database_path=tmp_path / "s.db", storage_path=tmp_path / "a", require_auth=True)
    app = create_app(settings)
    create_user(app.state.database, "alice", "correct-horse-battery", "accountant")
    create_user(app.state.database, "mallory", "another-long-password", "accountant")
    return app


def login(app, username, password):
    client = TestClient(app)
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client, {"X-CSRF-Token": response.json()["csrf_token"]}


def test_provisioning_grants_only_the_creator(secured):
    alice, alice_headers = login(secured, "alice", "correct-horse-battery")
    assert alice.post("/api/v1/scopes/provision", headers=alice_headers, json=new_scope()).status_code == 200

    mallory, mallory_headers = login(secured, "mallory", "another-long-password")
    listing = mallory.get("/api/v1/portfolio", headers=mallory_headers).json()
    assert listing.get("scopes", listing.get("items", [])) == []


def test_another_account_cannot_grant_itself_an_existing_scope(secured):
    """这是最关键的一条：新建可以自助，挤进别人已有的范围不行。"""
    alice, alice_headers = login(secured, "alice", "correct-horse-battery")
    alice.post("/api/v1/scopes/provision", headers=alice_headers, json=new_scope())

    mallory, mallory_headers = login(secured, "mallory", "another-long-password")
    response = mallory.post("/api/v1/scopes/provision", headers=mallory_headers, json=new_scope())
    assert response.status_code == 409
    with secured.state.database.connect() as connection:
        rows = connection.execute("SELECT user_id FROM auth_scope_grants").fetchall()
    assert [row["user_id"] for row in rows] == ["alice"]


def test_provisioned_scope_can_immediately_receive_material(secured):
    import base64
    alice, alice_headers = login(secured, "alice", "correct-horse-battery")
    body = new_scope()
    alice.post("/api/v1/scopes/provision", headers=alice_headers, json=body)
    from test_profile_driven_parsing import TERSE, workbook
    content = workbook([TERSE, ['2026-06-02', '', '100.00', '100.00', '甲', '货款']])
    response = alice.post("/api/v1/artifacts", headers=alice_headers, json={
        "scope": body, "filename": "流水.xlsx",
        "content_base64": base64.b64encode(content).decode(), "observed_period": body["accounting_period_id"]})
    assert response.status_code == 200, response.text
