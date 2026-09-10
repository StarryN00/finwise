from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal

import pytest

from app.ontology.contracts import FactInput, Scope, SourceAnchor
from app.ontology.enums import ObjectType
from app.ontology.errors import PreconditionFailed
from conftest import command
from test_delivery_safety import exported_package, ready_voucher
from test_system import build_demo


def fact_input(scope, fact):
    data = fact["data"]
    return FactInput(scope=scope, **{key: data[key] for key in (
        "source_artifact_id", "source_anchor", "record_type", "original_value",
        "normalized_value", "parser_version", "extraction_confidence", "period_check")})


def second_row(service, scope, fact, external_id, **amounts):
    value = fact_input(scope, fact)
    value.source_anchor = SourceAnchor(page=1, row=2, field=fact["data"]["record_type"].lower())
    value.normalized_value = {**value.normalized_value, "external_id": external_id, **amounts}
    value.original_value = {**value.original_value, "row": 2, "external_id": external_id}
    return service.create_fact_record(value, actor_id="alice")


def add_second_purchase(client, scope, **payment_values):
    demo = build_demo(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    invoice = next(f for f in demo["facts"] if f["data"]["record_type"] == "INVOICE")
    payment = next(f for f in demo["facts"] if f["data"]["record_type"] == "PAYMENT")
    inv2 = second_row(service, typed, invoice, "INV-002", invoice_total=2260, net_amount=2000, tax=260)
    pay2 = second_row(service, typed, payment, "PAY-002", **{"payment_total": 2260, **payment_values})
    group = service.create_procurement_business(typed, fact_ids=demo["group"]["data"]["member_fact_ids"] +
        [inv2["object_id"], pay2["object_id"]], business_identity="purchase-001", actor_id="alice")
    return service, typed, group, inv2, pay2


def test_fact_repeated_and_parallel_ingestion_has_one_stable_identity(client, scope):
    demo = build_demo(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    original = demo["facts"][1]
    value = fact_input(typed, original)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: service.create_fact_record(value, actor_id="alice"), range(4)))
    assert {f["object_id"] for f in results} == {original["object_id"]}
    assert all(f["version"] == original["version"] for f in results)
    assert len(service.store.list_objects(ObjectType.FACT_RECORD.value, typed)) == 4


def test_same_source_anchor_cannot_create_unmarked_conflicting_fact(client, scope):
    demo = build_demo(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    value = fact_input(typed, demo["facts"][1])
    value.normalized_value = {**value.normalized_value, "invoice_total": 9999}
    with pytest.raises(PreconditionFailed, match="重新解析"):
        service.create_fact_record(value, actor_id="alice")
    assert len(service.store.list_objects(ObjectType.FACT_RECORD.value, typed)) == 4


def test_archived_artifact_cannot_create_new_fact(client, scope):
    demo = build_demo(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    value = fact_input(typed, demo["facts"][1])
    artifact = service.store.get_object(value.source_artifact_id, typed)
    service.archive_artifact(typed, artifact_id=artifact["object_id"], expected_version=artifact["version"], actor_id="alice")
    value.source_anchor = SourceAnchor(row=99)
    with pytest.raises(PreconditionFailed):
        service.create_fact_record(value, actor_id="alice")


def test_all_invoices_and_payments_feed_checks_and_voucher(client, scope):
    service, typed, group, inv2, pay2 = add_second_purchase(client, scope)
    service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    group = service.store.get_object(group["object_id"], typed)
    service.confirm_grouping(typed, group_id=group["object_id"], expected_version=group["version"], actor_id="alice")
    checks = service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    assert all(c["result"] == "PASS" for c in checks)
    amounts = next(c for c in checks if c["check_type"] == "PAYMENT_INVOICE")["inputs"]
    assert float(amounts["invoice_total"]) == 3390
    assert len(amounts["invoices"]) == len(amounts["payments"]) == 2
    suggestion = service.agent_suggest_rule(typed, group_id=group["object_id"], actor_id="alice", model_output={
        "summary": "合成采购规则", "confidence": .9, "items": [{"debit_account": "库存商品", "credit_account": "银行存款"}],
        "evidence": group["data"]["evidence_ids"], "risk_level": "LOW", "next_action": "人工确认"})
    card = suggestion["confirmation_card"]
    service.approve_rule(typed, card_id=card["object_id"], expected_version=card["version"], actor_id="alice")
    voucher = service.generate_draft(typed, group_id=group["object_id"], actor_id="alice")
    assert [float(line["amount"]) for line in voucher["data"]["lines"]] == [3000, 390, 3390]
    assert inv2["object_id"] in [ref["fact_id"] for ref in voucher["data"]["fact_versions"]]
    assert pay2["object_id"] in [ref["fact_id"] for ref in voucher["data"]["fact_versions"]]
    assert service.validate_draft(typed, voucher_id=voucher["object_id"], expected_version=voucher["version"], actor_id="reviewer")["status"] == "LOCALLY_CONFIRMED"


@pytest.mark.parametrize("field,value,check_type", [
    ("payment_total", 2259, "PAYMENT_INVOICE"),
    ("tax", 259, "TAX"),
    ("invoice_total", 2261, "INVOICE_TOTAL"),
    ("tax_rate", None, "TAX"),
    ("invoice_total", "NaN", "INVOICE_TOTAL"),
    ("net_amount", "Infinity", "INVOICE_TOTAL"),
    ("payment_total", {}, "PAYMENT_INVOICE"),
    ("payment_total", True, "PAYMENT_INVOICE"),
    ("invoice_total", -2260, "INVOICE_TOTAL"),
])
def test_bad_second_record_blocks_without_ignoring_or_crashing(client, scope, field, value, check_type):
    service, typed, group, inv2, pay2 = add_second_purchase(client, scope)
    fact = pay2 if field == "payment_total" else inv2
    service.reparse_fact(typed, fact_id=fact["object_id"], expected_version=fact["version"],
        actor_id="alice", parser_version="test-v2", normalized_value={**fact["data"]["normalized_value"], field: value})
    checks = service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    assert any(c["check_type"] == check_type and c["result"] == "BLOCKED" for c in checks)
    assert service.store.get_object(group["object_id"], typed)["status"] == "BLOCKED"


def test_external_identity_duplicate_at_another_anchor_is_blocked(client, scope):
    demo = build_demo(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    invoice = next(f for f in demo["facts"] if f["data"]["record_type"] == "INVOICE")
    copy = second_row(service, typed, invoice, "INV-001")
    group = service.create_procurement_business(typed, fact_ids=[f["object_id"] for f in demo["facts"]]+[copy["object_id"]],
        business_identity="purchase-001", actor_id="alice")
    with pytest.raises(PreconditionFailed, match="重复"):
        service.confirm_grouping(typed, group_id=group["object_id"], expected_version=group["version"], actor_id="alice")


def test_cross_group_duplicate_cannot_bypass_primary_ownership_with_new_fact_ids(client, scope):
    demo = build_demo(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    group = demo["group"]
    service.confirm_grouping(typed, group_id=group["object_id"], expected_version=group["version"], actor_id="alice")
    copies = [second_row(service, typed, f, f["data"]["normalized_value"]["external_id"]) for f in demo["facts"]]
    other = service.create_procurement_business(typed, fact_ids=[f["object_id"] for f in copies], business_identity="purchase-copy", actor_id="alice")
    with pytest.raises(PreconditionFailed):
        service.confirm_grouping(typed, group_id=other["object_id"], expected_version=other["version"], actor_id="alice")


def test_invoice_and_bank_identifiers_use_separate_namespaces(client, scope):
    demo = build_demo(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    payment = next(f for f in demo["facts"] if f["data"]["record_type"] == "PAYMENT")
    service.reparse_fact(typed, fact_id=payment["object_id"], expected_version=payment["version"],
        actor_id="alice", parser_version="test-v2", normalized_value={**payment["data"]["normalized_value"], "external_id": "INV-001"})
    checks = service.reconcile_group(typed, group_id=demo["group"]["object_id"], actor_id="alice")
    assert next(c for c in checks if c["check_type"] == "DUPLICATE")["result"] == "PASS"


def test_new_reconciliation_cannot_reauthorize_old_voucher_source_versions(client, scope):
    service, typed, group, voucher = ready_voucher(client, scope)
    invoice = next(f for f in service.store.list_objects(ObjectType.FACT_RECORD.value, typed) if f["data"]["record_type"] == "INVOICE")
    values = deepcopy(invoice["data"]["normalized_value"])
    values["supplier_ref"] = "CORRECTED-SUPPLIER"
    service.reparse_fact(typed, fact_id=invoice["object_id"], expected_version=invoice["version"], actor_id="alice", parser_version="v2", normalized_value=values)
    service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    with pytest.raises(PreconditionFailed, match="凭证.*来源|来源.*凭证"):
        service.validate_draft(typed, voucher_id=voucher["object_id"], expected_version=voucher["version"], actor_id="reviewer")
    revised = service.generate_draft(typed, group_id=group["object_id"], actor_id="alice")
    assert revised["object_id"] == voucher["object_id"]
    assert revised["version"] == voucher["version"] + 1
    assert revised["status"] == "REVISED"
    assert service.store.get_object(voucher["object_id"], typed, voucher["version"]) == voucher
    assert service.validate_draft(typed, voucher_id=revised["object_id"], expected_version=revised["version"], actor_id="reviewer")["status"] == "LOCALLY_CONFIRMED"


def test_one_payment_can_cover_all_invoices_without_false_duplicate(client, scope):
    service, typed, group, inv2, pay2 = add_second_purchase(client, scope)
    data = deepcopy(group["data"])
    data["member_fact_ids"].remove(pay2["object_id"])
    group = service.store.revise_object(group["object_id"], group["version"], typed, data, status="CANDIDATE", created_by="alice")
    pay1 = next(service.store.get_object(fid, typed) for fid in data["member_fact_ids"] if service.store.get_object(fid, typed)["data"]["record_type"] == "PAYMENT")
    service.reparse_fact(typed, fact_id=pay1["object_id"], expected_version=pay1["version"], actor_id="alice", parser_version="v2", normalized_value={**pay1["data"]["normalized_value"], "payment_total": 3390})
    checks = service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    assert all(c["result"] == "PASS" for c in checks)
    inputs = next(c for c in checks if c["check_type"] == "PAYMENT_INVOICE")["inputs"]
    assert len(inputs["invoices"]) == 2 and len(inputs["payments"]) == 1


def test_fact_http_submission_reuses_identity_and_conflicts_are_visible(client, scope):
    demo = build_demo(client, scope)
    value = fact_input(Scope(**scope), demo["facts"][1]).model_dump(mode="json")
    first = client.post("/api/v1/facts", json=value)
    assert first.status_code == 200
    assert first.json()["object_id"] == demo["facts"][1]["object_id"]
    value["normalized_value"]["invoice_total"] = 1200
    conflict = client.post("/api/v1/facts", json=value)
    assert conflict.status_code == 409
    assert "重新解析" in conflict.json()["error"]["message"]


def test_new_source_parallel_first_ingestion_creates_one_fact(client, scope):
    demo = build_demo(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    value = fact_input(typed, demo["facts"][1])
    value.source_anchor = SourceAnchor(row=77)
    value.normalized_value = {**value.normalized_value, "external_id": "NEW-INV-077"}
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: service.create_fact_record(value, actor_id="alice"), range(4)))
    assert len({f["object_id"] for f in results}) == 1
    assert len(service.store.list_objects(ObjectType.FACT_RECORD.value, typed)) == 5


def test_legacy_fact_without_identity_is_reused_without_rewriting_history(client, scope):
    demo = build_demo(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    fact = demo["facts"][1]
    legacy_data = deepcopy(fact["data"])
    legacy_data.pop("source_identity")
    old = service.store.revise_object(fact["object_id"], fact["version"], typed, legacy_data, status="PARSED", created_by="fixture")
    result = service.create_fact_record(fact_input(typed, old), actor_id="alice")
    assert result == old
    assert len(service.store.list_objects(ObjectType.FACT_RECORD.value, typed)) == 4


def test_tax_errors_cannot_cancel_out_between_invoices(client, scope):
    service, typed, group, inv2, _ = add_second_purchase(client, scope)
    inv1 = next(f for f in service.store.list_objects(ObjectType.FACT_RECORD.value, typed)
                if f["data"]["record_type"] == "INVOICE" and f["object_id"] != inv2["object_id"])
    for fact, net, tax in ((inv1, 990, 140), (inv2, 2010, 250)):
        service.reparse_fact(typed, fact_id=fact["object_id"], expected_version=fact["version"], actor_id="alice", parser_version="v2",
            normalized_value={**fact["data"]["normalized_value"], "net_amount": net, "tax": tax})
    checks = service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    assert next(c for c in checks if c["check_type"] == "PAYMENT_INVOICE")["result"] == "PASS"
    assert next(c for c in checks if c["check_type"] == "TAX")["result"] == "BLOCKED"


def test_packaged_voucher_cannot_be_regenerated_after_source_change(client, scope):
    service, typed, group, voucher, exported = exported_package(client, scope)
    invoice = next(f for f in service.store.list_objects(ObjectType.FACT_RECORD.value, typed) if f["data"]["record_type"] == "INVOICE")
    service.reparse_fact(typed, fact_id=invoice["object_id"], expected_version=invoice["version"], actor_id="alice", parser_version="v2",
        normalized_value={**invoice["data"]["normalized_value"], "supplier_ref": "CORRECTED"})
    service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    with pytest.raises(PreconditionFailed, match="交付包"):
        service.generate_draft(typed, group_id=group["object_id"], actor_id="alice")
    assert service.store.get_object(voucher["object_id"], typed) == voucher
    assert service.store.get_object(exported["export"]["object_id"], typed) == exported["export"]


def test_multi_invoice_command_flow_exports_all_lines_and_retains_gate(client, scope):
    service, typed, group, _, _ = add_second_purchase(client, scope)

    def execute(action, obj, payload=None):
        response = command(client, scope, action, obj["object_id"], obj["version"], "multi-flow-" + action, payload)
        assert response.status_code == 200, response.text
        return response.json()["effect"]

    group = execute("confirm_grouping", group)["object"]
    execute("reconcile_group", group)
    group = service.store.get_object(group["object_id"], typed)
    suggested = service.agent_suggest_rule(typed, group_id=group["object_id"], actor_id="fixture", model_output={
        "summary": "仅合成测试规则", "confidence": .9, "items": [{"debit_account": "库存商品", "credit_account": "银行存款"}],
        "evidence": group["data"]["evidence_ids"], "risk_level": "LOW", "next_action": "人工核实"})
    execute("approve_rule", suggested["confirmation_card"])
    voucher = execute("generate_draft", service.store.get_object(group["object_id"], typed))["object"]
    voucher = execute("validate_draft", voucher)["object"]
    package = execute("release_delivery", service.store.get_object(group["object_id"], typed))["object"]
    exported = execute("export_package", package)
    assert exported["export"]["data"]["lines"] == voucher["data"]["lines"]
    assert sum(Decimal(line["amount"]) for line in exported["export"]["data"]["lines"] if line["direction"] == "CREDIT") == 3390
    assert service.workbench(typed)["period"]["status"] == "OPEN"


def test_large_group_preserves_cents_through_generation_review_and_export(client, scope):
    service, typed, group, original_voucher = ready_voucher(client, scope)
    facts = [service.store.get_object(fid, typed) for fid in group["data"]["member_fact_ids"]]
    member_ids = [f["object_id"] for f in facts if f["data"]["record_type"] not in {"INVOICE", "PAYMENT"}]
    for kind in ("INVOICE", "PAYMENT"):
        template = next(f for f in facts if f["data"]["record_type"] == kind)
        for i in range(71):
            value = fact_input(typed, template)
            value.source_anchor = SourceAnchor(row=i+100, field=kind.lower())
            amounts = {"invoice_total": "999999999999.99", "net_amount": "999999999999.99", "tax": "0.00", "tax_rate": "0"} if kind == "INVOICE" else {"payment_total": "999999999999.99"}
            value.normalized_value = {"external_id": f"{kind}-{i}", **amounts}
            fact = service.create_fact_record(value, actor_id="alice")
            member_ids.append(fact["object_id"])
    data = {**group["data"], "member_fact_ids": member_ids}
    current = service.store.get_object(group["object_id"], typed)
    service.store.revise_object(group["object_id"], current["version"], typed, data, status="CONFIRMED", created_by="alice")
    checks = service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    assert all(c["result"] == "PASS" for c in checks)
    voucher = service.generate_draft(typed, group_id=group["object_id"], actor_id="alice")
    assert voucher["data"]["lines"][0]["amount"] == "70999999999999.29"
    confirmed = service.validate_draft(typed, voucher_id=voucher["object_id"], expected_version=voucher["version"], actor_id="reviewer")
    assert confirmed["data"]["debit_total"] == confirmed["data"]["credit_total"] == "70999999999999.29"
    package = service.release_delivery(typed, group_id=group["object_id"], actor_id="reviewer")
    exported = service.export_package(typed, package_id=package["object_id"], actor_id="reviewer")
    assert exported["export"]["data"]["lines"][2]["amount"] == "70999999999999.29"


@pytest.mark.parametrize("kind,alias", [("INVOICE", "invoice_no"), ("PAYMENT", "transaction_id")])
@pytest.mark.parametrize("cross_group", [False, True])
def test_adding_specific_identifier_never_erases_existing_duplicate_alias(client, scope, kind, alias, cross_group):
    demo = build_demo(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    original = next(f for f in demo["facts"] if f["data"]["record_type"] == kind)
    if cross_group:
        group = demo["group"]
        service.confirm_grouping(typed, group_id=group["object_id"], expected_version=group["version"], actor_id="alice")
    duplicate = second_row(service, typed, original, original["data"]["normalized_value"]["external_id"], **{alias: "SPECIFIC-001"})
    if cross_group:
        members = []
        for f in demo["facts"]:
            copy = duplicate if f["object_id"] == original["object_id"] else second_row(service, typed, f, "COPY-" + f["data"]["record_type"])
            members.append(copy["object_id"])
    else:
        members = [f["object_id"] for f in demo["facts"]] + [duplicate["object_id"]]
        opposite = next(f for f in demo["facts"] if f["data"]["record_type"] == ("PAYMENT" if kind == "INVOICE" else "INVOICE"))
        amounts = {"payment_total": 2260} if kind == "INVOICE" else {"invoice_total": 2260, "net_amount": 2000, "tax": 260}
        service.reparse_fact(typed, fact_id=opposite["object_id"], expected_version=opposite["version"], actor_id="alice",
                             parser_version="v2", normalized_value={**opposite["data"]["normalized_value"], **amounts})
    group = service.create_procurement_business(typed, fact_ids=members,
        business_identity="purchase-copy" if cross_group else "purchase-001", actor_id="alice")
    with pytest.raises(PreconditionFailed, match="重复"):
        service.confirm_grouping(typed, group_id=group["object_id"], expected_version=group["version"], actor_id="alice")
    checks = service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    assert next(c for c in checks if c["check_type"] == "DUPLICATE")["result"] == "BLOCKED"
    assert all(c["result"] == "PASS" for c in checks if c["check_type"] != "DUPLICATE")


@pytest.mark.parametrize("account1,account2,expected", [("", "BANK-A", "BLOCKED"), ("BANK-A", "", "BLOCKED"),
    ("BANK-A", "bank-a", "BLOCKED"), ("BANK-A", "BANK-B", "PASS"),
    ("BANK-A", True, "BLOCKED"), ("BANK-A", {"value": None}, "BLOCKED"),
    ("BANK-A", ["BANK-B"], "BLOCKED"), ("BANK-A", 123, "BLOCKED"), ("BANK-A", "  ", "BLOCKED"),
    ("BANK-A", "BANK-A\u007f", "BLOCKED"), ("BANK-A", "BANK-A\u0080", "BLOCKED"),
    ("BANK-A", "BANK-A\u200b", "BLOCKED"), ("BANK-A", "BANK-A\n", "BLOCKED")])
def test_bank_local_identity_uses_known_accounts_without_hiding_unknown_duplicates(client, scope, account1, account2, expected):
    demo = build_demo(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    original = next(f for f in demo["facts"] if f["data"]["record_type"] == "PAYMENT")
    service.reparse_fact(typed, fact_id=original["object_id"], expected_version=original["version"], actor_id="alice",
        parser_version="v2", normalized_value={**original["data"]["normalized_value"], "bank_account_ref": account1})
    duplicate = second_row(service, typed, original, "PAY-001", account_ref=account2)
    invoice = next(f for f in demo["facts"] if f["data"]["record_type"] == "INVOICE")
    service.reparse_fact(typed, fact_id=invoice["object_id"], expected_version=invoice["version"], actor_id="alice", parser_version="v2",
        normalized_value={**invoice["data"]["normalized_value"], "invoice_total": 2260, "net_amount": 2000, "tax": 260})
    group = service.create_procurement_business(typed, fact_ids=[f["object_id"] for f in demo["facts"]]+[duplicate["object_id"]],
        business_identity="purchase-001", actor_id="alice")
    response = command(client, scope, "confirm_grouping", group["object_id"], group["version"], "bank-identity-confirm")
    assert response.status_code == (200 if expected == "PASS" else 409), response.text
    if expected == "BLOCKED":
        assert "重复" in response.json()["error"]["message"]
    checks = service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    assert next(c for c in checks if c["check_type"] == "DUPLICATE")["result"] == expected
    assert all(c["result"] == "PASS" for c in checks if c["check_type"] != "DUPLICATE")


def test_correction_commands_restore_ready_then_require_new_voucher_review(client, scope):
    service, typed, group, voucher = ready_voucher(client, scope)
    invoice = next(f for f in service.store.list_objects(ObjectType.FACT_RECORD.value, typed) if f["data"]["record_type"] == "INVOICE")

    def execute(action, object_id, key, payload=None):
        obj = service.store.get_object(object_id, typed)
        response = command(client, scope, action, object_id, obj["version"], key, payload)
        assert response.status_code == 200, response.text
        return response.json()["effect"]

    values = invoice["data"]["normalized_value"]
    execute("reparse_fact", invoice["object_id"], "correction-bad-tax", {"normalized_value": {**values, "tax": 129}})
    execute("reconcile_group", group["object_id"], "correction-block")
    assert service.store.get_object(group["object_id"], typed)["status"] == "BLOCKED"
    execute("reparse_fact", invoice["object_id"], "correction-good-tax", {"normalized_value": values})
    checks = execute("reconcile_group", group["object_id"], "correction-recover")["checks"]
    assert all(c["result"] == "PASS" for c in checks)
    restored = service.store.get_object(group["object_id"], typed)
    assert restored["status"] == "READY"
    assert "reconciliation_resume_status" not in restored["data"]
    response = command(client, scope, "validate_draft", voucher["object_id"], voucher["version"], "correction-old-review")
    assert response.status_code == 409
    revised = execute("generate_draft", group["object_id"], "correction-regenerate")["object"]
    assert revised["object_id"] == voucher["object_id"] and revised["status"] == "REVISED"
    assert revised["version"] == voucher["version"] + 1
    assert service.store.get_object(voucher["object_id"], typed, voucher["version"]) == voucher
    assert execute("validate_draft", revised["object_id"], "correction-new-review")["object"]["status"] == "LOCALLY_CONFIRMED"


@pytest.mark.parametrize("status,expected", [("CANDIDATE", "CANDIDATE"), ("SUSPENDED", "SUSPENDED"), ("BLOCKED", "BLOCKED")])
def test_reconciliation_recovery_preserves_unconfirmed_and_unrelated_holds(client, scope, status, expected):
    demo = build_demo(client, scope)
    service, typed = client.app.state.service, Scope(**scope)
    group, invoice = demo["group"], demo["facts"][1]
    service.store.revise_object(group["object_id"], group["version"], typed, group["data"], status=status, created_by="fixture")
    values = invoice["data"]["normalized_value"]
    bad = service.reparse_fact(typed, fact_id=invoice["object_id"], expected_version=invoice["version"], actor_id="alice",
        parser_version="bad", normalized_value={**values, "tax": 129})
    service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    assert service.store.get_object(group["object_id"], typed)["status"] == ("SUSPENDED" if status == "SUSPENDED" else "BLOCKED")
    service.reparse_fact(typed, fact_id=invoice["object_id"], expected_version=bad["version"], actor_id="alice", parser_version="fixed", normalized_value=values)
    checks = service.reconcile_group(typed, group_id=group["object_id"], actor_id="alice")
    assert all(c["result"] == "PASS" for c in checks)
    assert service.store.get_object(group["object_id"], typed)["status"] == expected
