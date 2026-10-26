"""识别卡的 HTTP 链路：上传 -> 解析认不出 -> 出卡 -> 确认 -> 重新解析出事实。"""
from __future__ import annotations

import base64

import pytest

from test_profile_driven_parsing import TERSE, TERSE_ROWS, workbook

HEADERS = {"X-Actor-Id": "alice", "X-Role": "accountant"}
LONG_ROWS = [
    ['2026-01-02', '', '1000.00', '1000.00', '甲公司', '货款'],
    ['2026-01-03', '400.00', '', '600.00', '乙公司', '手续费'],
    ['2026-01-04', '', '250.00', '850.00', '丙公司', '退款'],
    ['2026-01-05', '150.00', '', '700.00', '丁公司', '付款'],
    ['2026-01-06', '', '300.00', '1000.00', '戊公司', '收款'],
]


@pytest.fixture()
def prepared(client, scope):
    client.post("/api/v1/scopes", headers=HEADERS, json=scope)
    content = workbook([TERSE] + LONG_ROWS)
    response = client.post("/api/v1/artifacts", headers=HEADERS, json={
        "scope": scope, "filename": "某行流水.xlsx",
        "content_base64": base64.b64encode(content).decode(), "observed_period": scope["accounting_period_id"]})
    assert response.status_code == 200, response.text
    return response.json()


def parse(client, scope, artifact, key):
    return client.post("/api/v1/commands", headers=HEADERS, json={
        "action": "parse_artifact", "target_id": artifact["object_id"],
        "target_version": artifact["version"], "scope": scope,
        "idempotency_key": key, "payload": {"document_kind": "bank_statement"}})


def cards(client, scope):
    response = client.post("/api/v1/profile-cards", headers=HEADERS, json={"scope": scope})
    assert response.status_code == 200, response.text
    return response.json()


def test_no_cards_before_anything_is_parsed(client, scope):
    client.post("/api/v1/scopes", headers=HEADERS, json=scope)
    assert cards(client, scope) == {"cards": [], "count": 0}


def test_unrecognised_artifact_surfaces_exactly_one_card(client, scope, prepared):
    parse(client, scope, prepared, "first-parse-key")
    listing = cards(client, scope)
    assert listing["count"] == 1
    card = listing["cards"][0]
    assert card["card_type"] == "SOURCE_PROFILE_CONFIRM"
    assert card["artifact"]["id"] == prepared["object_id"]
    assert card["document_kind"] == "bank_statement" and card["sheet"] == "数据"
    assert card["why"]["origin"] == "AGENT" and card["why"]["yields"]["kind"] == "SOURCE_PROFILE"


def test_confirming_a_card_registers_a_profile_and_clears_the_queue(client, scope, prepared):
    parse(client, scope, prepared, "first-parse-key")
    card = cards(client, scope)["cards"][0]
    response = client.post("/api/v1/profile-cards/confirm", headers=HEADERS,
                           json={"scope": scope, "card": card})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["profile"]["origin"] == "HUMAN" and body["profile"]["confirmed_by"] == "alice"
    assert body["profile"]["scope_level"] == "ENTITY"
    assert cards(client, scope)["count"] == 0


def test_reparse_after_confirmation_produces_facts_from_the_profile(client, scope, prepared):
    first = parse(client, scope, prepared, "first-parse-key")
    assert first.json()["effect"]["facts"] == []
    card = cards(client, scope)["cards"][0]
    client.post("/api/v1/profile-cards/confirm", headers=HEADERS, json={"scope": scope, "card": card})

    artifact = first.json()["effect"]["artifact"]
    again = parse(client, scope, artifact, "after-confirm-key")
    assert again.status_code == 200, again.text
    effect = again.json()["effect"]
    assert len(effect["facts"]) == len(LONG_ROWS)
    assert effect["sheets"][0]["mapping_origin"] == "PROFILE"


def test_confirmation_is_recorded_in_the_audit_trail(client, scope, prepared):
    parse(client, scope, prepared, "first-parse-key")
    card = cards(client, scope)["cards"][0]
    client.post("/api/v1/profile-cards/confirm", headers=HEADERS, json={"scope": scope, "card": card})
    from app.ontology.contracts import Scope
    audits = client.app.state.service.store.list_audits(Scope(**scope))
    confirmations = [a for a in audits if a["event_type"] == "SOURCE_PROFILE_CONFIRMED"]
    assert len(confirmations) == 1 and confirmations[0]["actor_id"] == "alice"


def test_confirm_rejects_a_card_without_a_document_kind(client, scope, prepared):
    parse(client, scope, prepared, "first-parse-key")
    card = dict(cards(client, scope)["cards"][0])
    card.pop("document_kind")
    response = client.post("/api/v1/profile-cards/confirm", headers=HEADERS,
                           json={"scope": scope, "card": card})
    assert response.status_code == 400
    assert "资料类型" in response.text


def test_confirm_rejects_a_body_without_a_card(client, scope):
    client.post("/api/v1/scopes", headers=HEADERS, json=scope)
    response = client.post("/api/v1/profile-cards/confirm", headers=HEADERS, json={"scope": scope})
    assert response.status_code == 400


def test_a_profile_confirmed_in_one_entity_does_not_serve_another(client, scope, prepared):
    parse(client, scope, prepared, "first-parse-key")
    card = cards(client, scope)["cards"][0]
    client.post("/api/v1/profile-cards/confirm", headers=HEADERS, json={"scope": scope, "card": card})

    other = dict(scope, legal_entity_id="legal-b", baseline_id="baseline-b-2026-03")
    client.post("/api/v1/scopes", headers=HEADERS, json=other)
    content = workbook([TERSE] + LONG_ROWS)
    uploaded = client.post("/api/v1/artifacts", headers=HEADERS, json={
        "scope": other, "filename": "某行流水.xlsx",
        "content_base64": base64.b64encode(content).decode(),
        "observed_period": other["accounting_period_id"]}).json()
    parse(client, other, uploaded, "other-first-key")
    assert cards(client, other)["count"] == 1
