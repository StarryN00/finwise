"""从账套导出的余额表直接确认基线，全程走 HTTP 命令链路。"""
from __future__ import annotations

import base64
import glob
from pathlib import Path

import pytest

from app.ontology.contracts import Scope
from app.opening_balances import parse_balance_sheet, to_confirmation
from app.tabular import read_workbook
from conftest import command

REAL = glob.glob("/Users/starryn/dev/finwise/.data/荣鼎坤/*余额表_202601_202607*.xlsx")
HEADERS = {"X-Actor-Id": "alice", "X-Role": "accountant"}
pytestmark = pytest.mark.skipif(not REAL, reason="需要本地语料")


@pytest.fixture()
def prepared(client, scope):
    """把同一份 202607 余额表登记为期初来源与上期结账来源。"""
    scope = dict(scope, accounting_period_id="2026-08")
    client.post("/api/v1/scopes", headers=HEADERS, json=scope)
    content = Path(REAL[0]).read_bytes()
    uploads = {}
    for role, purpose in (("balance", "opening_balance"), ("close", "prior_close")):
        response = client.post("/api/v1/artifacts", headers=HEADERS, json={
            "scope": scope, "filename": f"{role}-余额表.xlsx",
            "content_base64": base64.b64encode(content).decode(),
            "observed_period": "2026-07", "source_purpose": purpose})
        assert response.status_code == 200, response.text
        uploads[role] = response.json()
    return scope, content, uploads


def test_the_candidate_compares_every_leaf_without_issues(client, prepared):
    scope, _, uploads = prepared
    response = client.post("/api/v1/baseline/candidate", headers=HEADERS, json={
        "scope": scope, "balance_artifact_id": uploads["balance"]["object_id"],
        "close_artifact_id": uploads["close"]["object_id"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["issues"] == []
    assert len(body["comparisons"]) == 80
    bank = [c for c in body["comparisons"] if c["account_code"] == "1002"]
    assert [c["auxiliary_key"] for c in bank] == ["江苏银行0758"]


def test_confirming_the_baseline_keeps_the_bank_account_opening(client, prepared):
    """基线必须具体到银行账户：101,017.78 正是 8 月对账单倒算出的期初。"""
    scope, content, uploads = prepared
    roots = parse_balance_sheet(read_workbook(content)[0])
    reference = lambda upload: {"artifact_id": upload["object_id"], "version": upload["version"],
                                "anchor": {"row": 1, "region": "余额表!1"}}
    payload = to_confirmation(roots, prior_period="2026-07", close_reference="余额表 202601至202607",
                              balance_source=reference(uploads["balance"]),
                              close_source=reference(uploads["close"]))
    baseline = client.app.state.service.workbench(Scope(**scope))["baseline"]
    response = command(client, scope, "confirm_baseline", baseline["object_id"],
                       baseline["version"], "baseline-real-0001", payload)
    assert response.status_code == 200, response.text

    confirmed = response.json()["effect"]["object"]
    assert confirmed["status"] == "CONFIRMED"
    data = confirmed["data"]
    assert data["balance_totals"] == {"debit": "1142245.37", "credit": "1142245.37"}
    assert len(data["confirmed_inputs"]["balances"]) == 22
    bank = next(b for b in data["confirmed_inputs"]["balances"] if b["account_code"] == "1002")
    account = next(a for a in bank["auxiliary"] if a["key"] == "江苏银行0758")
    assert account["opening_debit"] == "101017.78"


def test_the_workbench_reports_the_baseline_as_valid(client, prepared):
    scope, content, uploads = prepared
    roots = parse_balance_sheet(read_workbook(content)[0])
    reference = lambda upload: {"artifact_id": upload["object_id"], "version": upload["version"],
                                "anchor": {"row": 1, "region": "余额表!1"}}
    payload = to_confirmation(roots, prior_period="2026-07", close_reference="余额表 202601至202607",
                              balance_source=reference(uploads["balance"]),
                              close_source=reference(uploads["close"]))
    baseline = client.app.state.service.workbench(Scope(**scope))["baseline"]
    command(client, scope, "confirm_baseline", baseline["object_id"], baseline["version"],
            "baseline-real-0002", payload)
    workbench = client.post("/api/v1/workbench", headers=HEADERS, json={"scope": scope}).json()
    assert workbench["baseline_validation"]["status"] == "VALID"
