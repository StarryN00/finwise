"""凭证提案的 HTTP 链路：历史凭证是学习来源，不是本期事实。"""
from __future__ import annotations

import base64
import glob
from pathlib import Path

import pytest

HEADERS = {"X-Actor-Id": "alice", "X-Role": "accountant"}
JOURNAL = glob.glob("/Users/starryn/dev/finwise/.data/荣鼎坤/*序时账*")


def propose(client, scope):
    response = client.post("/api/v1/vouchers/propose", headers=HEADERS, json={"scope": scope})
    assert response.status_code == 200, response.text
    return response.json()


def test_without_history_the_system_says_so_instead_of_guessing(client, scope):
    client.post("/api/v1/scopes", headers=HEADERS, json=scope)
    body = propose(client, scope)
    assert body["proposals"] == [] and body["learned"] is None
    assert "历史凭证" in body["reason"]


@pytest.mark.skipif(not JOURNAL, reason="需要本地语料")
def test_history_is_learned_without_becoming_this_period_facts(client, scope):
    """把几百张往期凭证灌进事实库，既不属于这一期，也会把"还剩多少待处理"冲掉。"""
    scope = dict(scope, accounting_period_id="2026-08")
    client.post("/api/v1/scopes", headers=HEADERS, json=scope)
    content = Path(JOURNAL[0]).read_bytes()
    response = client.post("/api/v1/artifacts", headers=HEADERS, json={
        "scope": scope, "filename": "序时账.xlsx",
        "content_base64": base64.b64encode(content).decode(),
        "observed_period": "2026-07", "source_purpose": "historical_reference"})
    assert response.status_code == 200, response.text

    body = propose(client, scope)
    learned = body["learned"]
    assert learned["vouchers"] == 201, "只应学严格早于本期的凭证"
    assert learned["periods"][0] == "2026-01" and learned["periods"][-1] == "2026-07"
    assert learned["templates"] >= 40 and learned["accounts"] >= 30

    from app.ontology.contracts import Scope
    facts = client.app.state.service.store.list_objects("FactRecord", Scope(**scope))
    assert facts == [], "历史凭证不得变成本期事实"


@pytest.mark.skipif(not JOURNAL, reason="需要本地语料")
def test_the_current_period_is_never_used_to_learn_itself(client, scope):
    """用本期自己的凭证学再去生成本期，是循环论证，验不出任何东西。"""
    scope = dict(scope, accounting_period_id="2026-03")
    client.post("/api/v1/scopes", headers=HEADERS, json=scope)
    client.post("/api/v1/artifacts", headers=HEADERS, json={
        "scope": scope, "filename": "序时账.xlsx",
        "content_base64": base64.b64encode(Path(JOURNAL[0]).read_bytes()).decode(),
        "observed_period": "2026-02", "source_purpose": "historical_reference"})
    learned = propose(client, scope)["learned"]
    assert learned["periods"][-1] == "2026-02"
