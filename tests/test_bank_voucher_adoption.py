"""采纳流水凭证提案，并用对账单期末余额勾稽。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.ontology.contracts import Scope
from app.ontology.errors import PreconditionFailed, VersionConflict

HEADERS = {"X-Actor-Id": "alice", "X-Role": "accountant"}

LINES = [
    {"account_code": "560202", "account_name": "办公费", "debit": "91.53", "credit": "0.00"},
    {"account_code": "224101", "account_name": "侯文军", "debit": "0.00", "credit": "91.53"},
    {"account_code": "224101", "account_name": "侯文军", "debit": "91.53", "credit": "0.00"},
    {"account_code": "100201", "account_name": "江苏银行0758", "debit": "0.00", "credit": "91.53"},
]


def baseline_payload(source, opening="101017.78"):
    reference = {"artifact_id": source["object_id"], "version": source["version"],
                 "anchor": {"row": 1}}
    return {"prior_period": "2026-07", "close_reference": "SYNTHETIC", "currency": "CNY",
            "balance_source": reference, "close_source": reference, "completeness_confirmed": True,
            "balances": [
                {"account_code": "1002", "account_name": "银行存款",
                 "closing_debit": opening, "closing_credit": "0.00",
                 "opening_debit": opening, "opening_credit": "0.00",
                 "source_anchor": {"row": 1}, "requires_auxiliary": True,
                 "auxiliary": [{"key": "江苏银行0758", "account_code": "100201",
                                "closing_debit": opening, "closing_credit": "0.00",
                                "opening_debit": opening, "opening_credit": "0.00",
                                "source_anchor": {"row": 2}}]},
                {"account_code": "3001", "account_name": "实收资本",
                 "closing_debit": "0.00", "closing_credit": opening,
                 "opening_debit": "0.00", "opening_credit": opening,
                 "source_anchor": {"row": 3}, "requires_auxiliary": False, "auxiliary": []}]}


@pytest.fixture()
def ready(client, scope):
    """一个确认了基线、有一笔银行流水事实的处理范围。"""
    import base64
    from app.ontology.service import ObjectType
    scope = dict(scope, accounting_period_id="2026-08")
    client.post("/api/v1/scopes", headers=HEADERS, json=scope)
    source = client.post("/api/v1/artifacts", headers=HEADERS, json={
        "scope": scope, "filename": "余额表.txt",
        "content_base64": base64.b64encode(b"SYNTHETIC").decode(),
        "observed_period": "2026-07", "source_purpose": "opening_balance"}).json()

    service = client.app.state.service
    typed = Scope(**scope)
    baseline = service.workbench(typed)["baseline"]
    from conftest import command
    response = command(client, scope, "confirm_baseline", baseline["object_id"],
                       baseline["version"], "adopt-baseline-1", baseline_payload(source))
    assert response.status_code == 200, response.text

    fact = service.store.create_initial_object(
        ObjectType.FACT_RECORD.value, typed,
        {"record_type": "PAYMENT", "source_artifact_id": source["object_id"],
         "source_anchor": {"row": 31},
         "normalized_value": {"transaction_date": "2026-08-28", "summary": "购买矿泉水",
                              "counterparty": "侯文军", "expense": "91.53", "income": "0.00"},
         "parser_version": "t", "extraction_confidence": 1.0, "period_check": "PASS"},
        status="PARSED", created_by="fixture")
    return scope, fact


def adopt(client, scope, fact, lines=None, **kw):
    payload = {"scope": scope, "fact_id": fact["object_id"],
               "fact_version": kw.pop("fact_version", fact["version"]),
               "lines": lines if lines is not None else LINES,
               "summary": "报销", "basis": ["学自 33 张历史凭证"]}
    payload.update(kw)
    return client.post("/api/v1/vouchers/adopt", headers=HEADERS, json=payload)


# ---------- 采纳 ----------

def test_adopting_a_proposal_creates_a_draft_bound_to_the_source(client, ready):
    scope, fact = ready
    response = adopt(client, scope, fact)
    assert response.status_code == 200, response.text
    voucher = response.json()["voucher"]
    assert voucher["status"] == "DRAFT"
    assert voucher["data"]["source_fact_id"] == fact["object_id"]
    assert voucher["data"]["source_fact_version"] == fact["version"]
    assert voucher["data"]["debit_total"] == voucher["data"]["credit_total"] == "183.06"
    # 采纳只是记下了做法，不等于账已经正式入库。
    assert voucher["data"]["formal_balance_impact"] is False


def test_the_basis_is_kept_with_the_voucher(client, ready):
    scope, fact = ready
    voucher = adopt(client, scope, fact).json()["voucher"]
    assert voucher["data"]["adoption_basis"] == ["学自 33 张历史凭证"]
    assert voucher["data"]["adopted_by"] == "alice"


def test_adopting_twice_returns_the_same_voucher_instead_of_posting_again(client, ready):
    scope, fact = ready
    first = adopt(client, scope, fact).json()["voucher"]
    second = adopt(client, scope, fact).json()["voucher"]
    assert first["object_id"] == second["object_id"]


def test_an_unbalanced_voucher_is_refused(client, ready):
    scope, fact = ready
    lines = [dict(LINES[0]), dict(LINES[1], credit="90.00")]
    response = adopt(client, scope, fact, lines=lines)
    assert response.status_code == 409 and "借贷不平" in response.text


def test_a_line_with_both_or_neither_direction_is_refused(client, ready):
    scope, fact = ready
    both = [dict(LINES[0], credit="1.00"), LINES[1]]
    assert adopt(client, scope, fact, lines=both).status_code == 409
    neither = [dict(LINES[0], debit="0.00"), LINES[1]]
    assert adopt(client, scope, fact, lines=neither).status_code == 409


def test_a_single_line_voucher_is_refused(client, ready):
    scope, fact = ready
    assert adopt(client, scope, fact, lines=[LINES[0]]).status_code == 409


def test_a_line_without_an_account_is_refused(client, ready):
    scope, fact = ready
    lines = [dict(LINES[0], account_code=""), LINES[1]]
    assert adopt(client, scope, fact, lines=lines).status_code == 409


def test_a_stale_source_version_is_refused(client, ready):
    """流水重新识别后，照着旧识别结果做的凭证必须失效重做。"""
    scope, fact = ready
    response = adopt(client, scope, fact, fact_version=fact["version"] + 1)
    assert response.status_code == 409 and "版本" in response.text


def test_a_non_bank_fact_cannot_take_this_path(client, ready):
    from app.ontology.service import ObjectType
    scope, _ = ready
    typed = Scope(**scope)
    invoice = client.app.state.service.store.create_initial_object(
        ObjectType.FACT_RECORD.value, typed,
        {"record_type": "INVOICE", "source_artifact_id": "x", "source_anchor": {"row": 1},
         "normalized_value": {"invoice_total": "100.00"}, "parser_version": "t",
         "extraction_confidence": 1.0, "period_check": "PASS"},
        status="PARSED", created_by="fixture")
    response = adopt(client, scope, invoice)
    assert response.status_code == 409 and "银行流水" in response.text


# ---------- 勾稽 ----------

def reconcile(client, scope):
    return client.post("/api/v1/vouchers/reconciliation", headers=HEADERS,
                       json={"scope": scope}).json()


def test_reconciliation_reports_what_is_still_missing(client, ready):
    scope, fact = ready
    before = reconcile(client, scope)
    assert before["opening"] == "101017.78"
    assert before["outstanding"] == 1 and before["adopted_vouchers"] == 0

    adopt(client, scope, fact)
    after = reconcile(client, scope)
    assert after["adopted_vouchers"] == 1 and after["outstanding"] == 0
    assert after["movement"] == "-91.53"
    assert after["computed_closing"] == "100926.25"


def test_reconciliation_needs_a_baseline_before_it_can_say_anything(client, scope):
    client.post("/api/v1/scopes", headers=HEADERS, json=scope)
    body = reconcile(client, scope)
    assert body["status"] == "NO_BASELINE"


def test_only_the_named_bank_account_moves_the_balance(client, ready):
    """凭证里其他科目的借贷不该影响银行余额 —— 只认那个账户的分录。"""
    scope, fact = ready
    adopt(client, scope, fact)
    body = reconcile(client, scope)
    assert body["bank_account"] == {"code": "100201", "name": "江苏银行0758"}
    assert Decimal(body["movement"]) == Decimal("-91.53")


def test_an_unconfirmed_baseline_is_named_as_such(client, scope):
    """基线对象随处理范围一起创建，存在不等于已确认。
    报"没有银行科目"会把人引去查科目表，而真正要做的是确认期初。"""
    client.post("/api/v1/scopes", headers=HEADERS, json=scope)
    body = reconcile(client, scope)
    assert body["status"] == "NO_BASELINE" and "尚未确认" in body["reason"]
