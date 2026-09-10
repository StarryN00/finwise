"""Historical originals are prepared automatically, never approved by a worker."""
import base64
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.ontology.contracts import ArtifactInput, Scope
from app.ontology.errors import PreconditionFailed
from app.historical import prepare_workbooks, HistoricalPreparation
from app import historical
from conftest import command
from test_tabular_ingestion import xlsx_fixture


def workbooks(*, credit=100, period="2025年01月至2025年12月", auxiliary=False, auxiliary_complete=False, currency=None, foreign_total=None):
    balance = xlsx_fixture([("余额表", [
        ["科目余额表"], ["编制单位：测试企业", f"币别：{currency}" if currency else None], [period, "单位：元"],
        ["科目编码", "科目名称", "期初余额", None, "本期发生额", None, "期末余额", None],
        [None, None, "借方", "贷方", "借方", "贷方", "借方", "贷方"],
        ["1002", "银行存款", 0, 0, 100, 0, 100, 0],
        ["1002001", "测试银行", 0, 0, 100, 0, 100, 0],
        *([["1002001.001", "测试银行.测试人员", 0, 0, 100, 0, 100, 0]] if auxiliary_complete else []),
        ["4001", "实收资本", 0, 0, 0, credit, 0, credit],
        [None, "合计", 0, 0, 100, credit, 100, credit],
    ])])
    journal = xlsx_fixture([("序时账", [
        ["序时账"], [period],
        ["日期", "凭证字号", "摘要", "科目全称", "科目编码", "科目名称", "数量", "外币", "借方金额", "贷方金额", "人员编码", "人员"],
        ["2025-12-31", "记-001", "入资", "银行存款_测试银行", "1002001", "测试银行", None, None, 100, 0, "001" if auxiliary else None, "测试人员" if auxiliary else None],
        ["2025-12-31", "记-001", "入资", "实收资本", "4001", "实收资本", None, None, 0, credit],
        [None, None, "合计", None, None, None, None, foreign_total, 100, credit],
    ])])
    return balance, journal


def upload(service, scope, data, name):
    return service.create_artifact(ArtifactInput(scope=scope, filename=name,
        content_base64=base64.b64encode(data).decode(), observed_period="2025-12",
        source_purpose="historical_reference"), actor_id="fixture")


def setup(client, scope, **kwargs):
    typed = Scope(**{**scope, "accounting_period_id": "2026-01"})
    service = client.app.state.service
    service.create_scope(typed)
    balance, journal = workbooks(**kwargs)
    sources = [upload(service, typed, balance, "余额.xlsx"), upload(service, typed, journal, "序时.xlsx")]
    return service, typed, sources


def test_parser_uses_year_end_not_year_opening_and_does_not_double_count():
    result = prepare_workbooks(*workbooks(), "2026-01")
    assert not result["issues"]
    assert result["account_count"] == 3
    assert result["leaf_count"] == 2
    assert result["totals"] == {"debit": "100.00", "credit": "100.00"}
    assert result["balances"][0]["opening_debit"] == "100.00"
    assert result["balances"][0]["source_anchor"]["row"] == 7
    assert result["entry_count"] == 2 and result["voucher_count"] == 1


def unmapped_workbooks():
    balance, journal = workbooks()
    rows = historical.read_workbook(journal)[0]["rows"]
    values = [r["values"] for r in rows]
    values[3][4] = "9999"
    values.insert(5, ["2025-12-31", "记-002", "调整核对", "待核对科目", "9999", "待核对科目", None, None, -100, 0])
    values.insert(6, ["2025-12-31", "记-002", "调整核对", "银行存款_测试银行", "1002001", "测试银行", None, None, 100, 0])
    return balance, xlsx_fixture([("序时账", values)])


def test_issue_view_exposes_actual_rows_and_related_voucher_without_mutating_job(client, scope):
    service=client.app.state.service
    typed=Scope(**{**scope,"accounting_period_id":"2026-01"})
    service.create_scope(typed)
    for name,data in zip(("余额.xlsx","序时.xlsx"),unmapped_workbooks()):
        upload(service,typed,data,name)
    service.historical.run_once()
    before=service.historical.get(typed)
    assert before["status"]=="NEEDS_REVIEW"
    issue=service.historical.view(typed)["data"]["result"]["issues"][0]
    assert issue["code"]=="UNMAPPED_ACCOUNT"
    evidence=issue["evidence"]
    assert evidence["summary"]["debit_positive"]=="100.00"
    assert evidence["summary"]["debit_negative"]=="-100.00"
    assert evidence["summary"]["net_movement"]=="0.00"
    assert evidence["rows"][0]["summary"]=="调整核对"
    assert evidence["rows"][0]["debit"]=="-100.00"
    assert evidence["rows"][0]["source"]["filename"]=="序时.xlsx"
    projected=service.historical.view(typed)["data"]["result"]
    assert [r["account_code"] for r in projected["evidence_vouchers"][0]["rows"]]==["9999","1002001"]
    assert "记-002" in evidence["advice"][0] and "不自动补零" in evidence["advice"][-1]
    assert service.historical.get(typed)==before
    assert service.workbench(typed)["baseline"]["status"]=="DRAFT"
    other=Scope(**{**typed.model_dump(),"legal_entity_id":"other"})
    service.create_scope(other)
    assert service.historical.view(other) is None
    source=service.store.get_object(evidence["rows"][0]["source"]["artifact_id"],typed)
    (service.store.database.settings.storage_path/source["data"]["storage_path"]).write_bytes(b"tampered")
    stale=service.historical.view(typed)
    assert stale["status"]=="STALE" and stale["data"]["result"] is None


def test_issue_evidence_does_not_guess_ambiguous_or_missing_locations():
    b,j=unmapped_workbooks()
    result=prepare_workbooks(b,j,"2026-01")
    refs=[({"artifact_id":"b","version":1,"sha256":"b","filename":"b.xlsx"},b),
          ({"artifact_id":"j","version":1,"sha256":"j","filename":"j.xlsx"},j)]
    issue=next(i for i in result["issues"] if i["code"]=="UNMAPPED_ACCOUNT")
    issue["anchors"].append({"region":"不明!第99行","row":99})
    evidence=historical.issue_evidence({"issues":[issue]},refs)["issues"][0]["evidence"]
    assert evidence["missing_locations"]==1 and evidence["summary"] is None
    ambiguous=historical.issue_evidence({"issues":[issue]},refs+[({**refs[1][0],"artifact_id":"another"},j)])["issues"][0]["evidence"]
    assert not ambiguous["rows"] and ambiguous["summary"] is None


def test_shared_voucher_context_is_deduplicated_and_projection_is_bounded():
    b,j=unmapped_workbooks()
    issue=prepare_workbooks(b,j,"2026-01")["issues"][0]
    refs=[({"artifact_id":"b","filename":"b.xlsx"},b),({"artifact_id":"j","filename":"j.xlsx"},j)]
    projection=historical.issue_evidence({"issues":[issue]*600},refs)
    assert len(projection["evidence_vouchers"])==1
    assert len({i["evidence"]["related_vouchers"][0]["context_id"] for i in projection["issues"]})==1
    count=sum(len(i["evidence"]["rows"]) for i in projection["issues"])+sum(len(v["rows"]) for v in projection["evidence_vouchers"])
    assert count<=1000
    assert any(i["evidence"]["omitted_rows"] for i in projection["issues"])
    assert all(i["evidence"]["summary"]["record_count"]==2 for i in projection["issues"])


def test_parser_blocks_differences_and_missing_auxiliary():
    assert prepare_workbooks(*workbooks(credit=99), "2026-01")["issues"]
    result = prepare_workbooks(*workbooks(auxiliary=True), "2026-01")
    assert any(i["code"] == "AUXILIARY_REQUIRED" for i in result["issues"])
    complete = prepare_workbooks(*workbooks(auxiliary=True, auxiliary_complete=True), "2026-01")
    assert not complete["issues"]
    assert complete["auxiliary_count"] == 1
    assert complete["balances"][0]["auxiliary"][0]["opening_debit"] == "100.00"


def test_parser_rejects_wrong_period():
    with pytest.raises(ValueError, match="期间"):
        prepare_workbooks(*workbooks(), "2026-03")


@pytest.mark.parametrize("currency", ["USD","美元","港币","CNY/USD","CNY\n币别：USD","CNY\r\nCURRENCY:USD"])
def test_explicit_foreign_currency_never_becomes_cny(currency):
    with pytest.raises(ValueError, match="币种"):
        prepare_workbooks(*workbooks(currency=currency), "2026-01")


def test_foreign_currency_in_journal_total_is_not_skipped():
    with pytest.raises(ValueError, match="外币金额"):
        prepare_workbooks(*workbooks(foreign_total=25), "2026-01")


def test_cny_and_numeric_xls_codes_are_supported_without_truncation(monkeypatch):
    read = historical.read_workbook
    def numeric_codes(content):
        sheets=read(content)
        for s in sheets:
            index=0 if s["rows"][0]["values"][0]=="科目余额表" else 4
            for row in s["rows"]:
                if len(row["values"])>index and str(row["values"][index]).isdigit():
                    row["values"][index]=float(row["values"][index])
        return sheets
    monkeypatch.setattr(historical,"read_workbook",numeric_codes)
    assert not prepare_workbooks(*workbooks(currency="CNY"),"2026-01")["issues"]
    assert historical.code_text("001002")=="001002"
    with pytest.raises(ValueError):
        historical.code_text(1002.5)


def test_duplicate_upload_repairs_enqueue_failure_without_restart(client,scope,monkeypatch):
    service=client.app.state.service
    typed=Scope(**{**scope,"accounting_period_id":"2026-01"})
    service.create_scope(typed)
    enqueue=service.historical.enqueue
    def failed(*args,**kwargs):
        raise RuntimeError("simulated queue interruption")
    monkeypatch.setattr(service.historical,"enqueue",failed)
    original = workbooks()[0]
    with pytest.raises(RuntimeError):
        upload(service,typed,original,"余额.xlsx")
    assert service.historical.get(typed) is None
    monkeypatch.setattr(service.historical,"enqueue",enqueue)
    upload(service,typed,original,"余额.xlsx")
    assert service.historical.get(typed)["status"]=="QUEUED"
    assert len(service.store.list_objects("SourceArtifact",typed))==1


def test_upload_queues_and_worker_keeps_originals_and_baseline_unconfirmed(client, scope):
    service, typed, sources = setup(client, scope)
    runner = service.historical
    job = runner.get(typed)
    assert job["status"] == "QUEUED"
    assert runner.run_once()
    ready = runner.get(typed)
    assert ready["status"] == "READY_FOR_CONFIRMATION"
    assert ready["data"]["result"]["totals"]["debit"] == "100.00"
    overview = service.workbench(typed)
    assert overview["baseline"]["status"] == "DRAFT"
    assert overview["counts"]["facts"] == 0
    assert not overview["vouchers"] and not overview["history_runs"]
    assert [service.store.get_object(s["object_id"], typed) for s in sources] == sources
    assert not runner.run_once()
    # Reuse the original bytes: rebuilding XLSX can change ZIP timestamps.
    original = (service.store.database.settings.storage_path / sources[0]["data"]["storage_path"]).read_bytes()
    same = upload(service, typed, original, "余额重复.xlsx")
    assert same["object_id"] == sources[0]["object_id"]
    assert runner.get(typed)["version"] == ready["version"]


def test_missing_and_ambiguous_files_are_not_running(client, scope):
    service = client.app.state.service
    typed = Scope(**{**scope, "accounting_period_id": "2026-01"})
    service.create_scope(typed)
    balance, journal = workbooks()
    upload(service, typed, balance, "余额.xlsx")
    service.historical.run_once()
    assert service.historical.get(typed)["status"] == "WAITING_INPUT"
    upload(service, typed, journal, "序时.xlsx")
    upload(service, typed, workbooks(credit=99)[0], "另一个余额.xlsx")
    service.historical.run_once()
    assert service.historical.get(typed)["status"] == "NEEDS_SELECTION"


def test_selected_pair_survives_duplicate_upload(client, scope):
    service, typed, sources=setup(client,scope)
    upload(service,typed,workbooks(credit=99)[0],"旧版余额.xlsx")
    service.historical.enqueue(typed,"fixture",artifact_ids=[s["object_id"] for s in sources])
    service.historical.run_once()
    job=service.historical.get(typed)
    assert job["status"]=="READY_FOR_CONFIRMATION"
    upload(service,typed,workbooks()[0],"余额重传.xlsx")
    assert service.historical.get(typed)==job


def test_explicit_confirmation_is_version_bound_and_rejects_tampering(client, scope):
    service, typed, sources = setup(client, scope)
    service.historical.run_once()
    job = service.historical.get(typed)
    baseline = service.workbench(typed)["baseline"]
    payload = {"historical_preparation": {"object_id": job["object_id"], "version": job["version"]},
               "completeness_confirmed": True, "final_close_confirmed": True, "carry_forward_confirmed": True}
    rejected = command(client, typed.model_dump(), "confirm_baseline", baseline["object_id"], baseline["version"], "missing-human-flags", {**payload, "final_close_confirmed": False})
    assert rejected.status_code == 409
    response = command(client, typed.model_dump(), "confirm_baseline", baseline["object_id"], baseline["version"], "confirm-historical-good", payload)
    assert response.status_code == 200, response.text
    assert service.workbench(typed)["baseline_validation"]["status"] == "VALID"
    path = service.store.database.settings.storage_path / sources[0]["data"]["storage_path"]
    path.write_bytes(b"corrupt fixture")
    assert service.workbench(typed)["baseline_validation"]["status"] == "INVALID"


def test_cannot_bypass_historical_validation_with_legacy_manual_payload(client, scope):
    service, typed, _ = setup(client, scope)
    service.historical.run_once()
    job = service.historical.get(typed)
    valid = {"historical_preparation": {"object_id": job["object_id"], "version": job["version"]},
             "completeness_confirmed": True, "final_close_confirmed": True, "carry_forward_confirmed": True}
    payload = service.historical.confirmation_inputs(typed, valid)
    baseline = service.workbench(typed)["baseline"]
    response = command(client, typed.model_dump(), "confirm_baseline", baseline["object_id"], baseline["version"], "legacy-history-bypass", payload)
    assert response.status_code == 409
    assert "不能绕过" in response.text


def test_auxiliary_gap_cannot_be_approved_and_archived_source_invalidates_candidate(client, scope):
    service, typed, sources = setup(client, scope, auxiliary=True)
    service.historical.run_once()
    job = service.historical.get(typed)
    assert job["status"] == "NEEDS_REVIEW"
    with pytest.raises(PreconditionFailed):
        service.historical.confirmation_inputs(typed, {"historical_preparation": {"object_id": job["object_id"], "version": job["version"]},
            "completeness_confirmed": True, "final_close_confirmed": True, "carry_forward_confirmed": True})
    service.archive_artifact(typed, artifact_id=sources[0]["object_id"], expected_version=1, actor_id="fixture")
    assert service.workbench(typed)["historical_preparation"]["status"] == "STALE"


def test_failure_retry_and_lost_worker_recovery(client, scope):
    service, typed, sources = setup(client, scope)
    runner = service.historical
    path = service.store.database.settings.storage_path / sources[0]["data"]["storage_path"]
    original = path.read_bytes()
    path.write_bytes(b"corrupt fixture")
    runner.run_once()
    assert runner.get(typed)["status"] == "FAILED"
    path.write_bytes(original)
    runner.enqueue(typed, "fixture", retry=True)
    # A process dies after claiming; an expired lease is reclaimed by another worker.
    claimed = runner.claim()
    data = {**claimed["data"], "lease_until": time.time()-1}
    service.store.revise_object(claimed["object_id"], claimed["version"], typed, data, status="RUNNING", created_by="fixture")
    HistoricalPreparation(service).run_once()
    assert runner.get(typed)["status"] == "READY_FOR_CONFIRMATION"


def test_only_one_worker_can_claim_and_stale_result_cannot_publish(client, scope):
    service, typed, _ = setup(client, scope)
    runner = service.historical
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: runner.claim(), range(2)))
    assert sum(x is not None for x in claims) == 1
    claimed = next(c for c in claims if c)
    upload(service, typed, workbooks(credit=99)[0], "新余额.xlsx")
    assert not runner.finish(claimed, "READY_FOR_CONFIRMATION", {"result": {}})


def test_job_scope_and_readonly_role_are_enforced(client, scope):
    service, typed, _ = setup(client, scope)
    job = service.historical.get(typed)
    other = Scope(**{**typed.model_dump(), "legal_entity_id": "another"})
    service.create_scope(other)
    assert service.historical.get(other) is None
    baseline = service.workbench(typed)["baseline"]
    response = command(client, typed.model_dump(), "prepare_historical", baseline["object_id"], baseline["version"], "readonly-prepare", {}, role="viewer")
    assert response.status_code == 403
    with pytest.raises(Exception):
        service.historical.confirmation_inputs(other, {"historical_preparation": {"object_id": job["object_id"], "version": job["version"]}})
    with pytest.raises(PreconditionFailed):
        service.historical.enqueue(typed,"fixture",artifact_ids=[{},{}])


def test_startup_repairs_a_durable_upload_queue_gap(client, scope):
    service, typed, _ = setup(client, scope)
    service.historical.run_once()
    # Simulate a crash between an appended artifact and enqueue using a stale cohort.
    job=service.historical.get(typed)
    service.store.revise_object(job["object_id"],job["version"],typed,{**job["data"],"cohort_hash":"stale"},status=job["status"],created_by="fixture")
    service.historical.start()
    try:
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and service.historical.get(typed)["status"] in {"QUEUED","RUNNING"}:
            time.sleep(.05)
        assert service.historical.get(typed)["version"]>job["version"]+1
        assert service.historical.get(typed)["status"]=="READY_FOR_CONFIRMATION"
    finally:
        service.historical.stop()


def test_real_lifespan_automatically_processes_upload_without_clicking(app, scope):
    with TestClient(app) as client:
        service, typed, _ = setup(client, scope)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and service.historical.get(typed)["status"] in {"QUEUED", "RUNNING"}:
            time.sleep(.05)
        assert service.historical.get(typed)["status"] == "READY_FOR_CONFIRMATION"
