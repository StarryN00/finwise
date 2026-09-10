import base64

from app.ontology.contracts import ArtifactInput, Scope
from conftest import command
from test_tabular_ingestion import xlsx_fixture


HEADERS = ["科目编码", "科目名称", "期末借方", "期末贷方", "期初借方", "期初贷方", "是否辅助核算", "辅助核算项"]


def source(service, scope, filename, rows):
    return service.create_artifact(
        ArtifactInput(
            scope=scope,
            filename=filename,
            content_base64=base64.b64encode(xlsx_fixture([("余额表", [HEADERS, *rows])])).decode(),
            observed_period="2026-02",
        ),
        actor_id="fixture",
    )


def test_baseline_candidate_compares_prior_workbooks_and_confirms_from_generated_payload(client, scope):
    service, typed = client.app.state.service, Scope(**scope)
    service.create_scope(typed, actor_id="fixture")
    opening = source(service, typed, "2026-03期初余额.xlsx", [
        ["1001", "库存现金", "1000", "0", "1000", "0", "否", None],
        ["4001", "实收资本", "0", "1000", "0", "1000", "否", None],
    ])
    closing = source(service, typed, "2026-02期末余额.xlsx", [
        ["1001", "库存现金", "1000", "0", "1000", "0", "否", None],
        ["4001", "实收资本", "0", "1000", "0", "1000", "否", None],
    ])

    response = client.post("/api/v1/baseline/candidate", json={
        "scope": scope, "balance_artifact_id": opening["object_id"], "close_artifact_id": closing["object_id"],
    })
    assert response.status_code == 200, response.text
    candidate = response.json()
    assert candidate["status"] == "READY_FOR_CONFIRMATION"
    assert candidate["line_count"] == candidate["matched_lines"] == 2
    assert candidate["totals"] == {"opening_debit": "1000.00", "opening_credit": "1000.00", "closing_debit": "1000.00", "closing_credit": "1000.00"}
    assert candidate["confirmation_payload"]["completeness_confirmed"] is False
    assert candidate["comparisons"][0]["opening"]["source_anchor"]["row"] == 2

    payload = candidate["confirmation_payload"]
    payload["completeness_confirmed"] = True
    baseline = service.workbench(typed)["baseline"]
    confirmed = command(client, scope, "confirm_baseline", baseline["object_id"], baseline["version"], "baseline-from-source-001", payload)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["effect"]["object"]["status"] == "CONFIRMED"


def test_baseline_candidate_blocks_mismatched_or_incomplete_prior_lines(client, scope):
    service, typed = client.app.state.service, Scope(**scope)
    service.create_scope(typed, actor_id="fixture")
    opening = source(service, typed, "期初.xlsx", [["1001", "库存现金", "900", "0", "900", "0", "否", None]])
    closing = source(service, typed, "期末.xlsx", [["1001", "库存现金", "1000", "0", "1000", "0", "否", None]])
    response = client.post("/api/v1/baseline/candidate", json={
        "scope": scope, "balance_artifact_id": opening["object_id"], "close_artifact_id": closing["object_id"],
    })
    assert response.status_code == 200, response.text
    candidate = response.json()
    assert candidate["status"] == "BLOCKED"
    assert any("不一致" in item for item in candidate["issues"])
    assert candidate["review_lines"] == 1
