import pytest

from app.issue_triage import STATUS_ISSUE, classify_task


def descriptor(*option_ids, focus="field"):
    return {
        "presentation": {
            "type_label": "契约问题标题",
            "explanation": "契约问题解释",
            "records": [{"id": "row-1", "focus_fields": [focus]}],
        },
        "options": [{"id": option_id, "available": True} for option_id in option_ids],
    }


def row(*, field="field", state="DIRECT_MATCH", value="已定位", opinion=None):
    result = {
        "object_id": "row-1",
        "source_anchor": {"region": "Sheet1!A2"},
        "values": {field: value, "invoice_no": "INV-1"},
        "comparison": [{
            "field": field,
            "state": state,
            "value": value,
            "region": "Sheet1!A2",
            "source_value": value,
        }],
    }
    if opinion:
        result["bill_confirmation"] = {"status": opinion}
    return result


def task(kind="ISSUE", reason="未知字段：需要判断", *, options=("supplement",), focus="field"):
    return {
        "kind": kind,
        "reason": reason,
        "title": "原任务标题",
        "record_ids": ["row-1"],
        "descriptor": descriptor(*options, focus=focus),
    }


@pytest.mark.parametrize(
    ("name", "value", "rows", "checks", "source_valid", "route", "human_ready", "title", "question"),
    [
        ("invalid-source", task(), [row()], [], False, "SYSTEM", False, "契约问题标题", None),
        ("parse", task("PARSE"), [row()], [], True, "SYSTEM", False, "资料识别待检查", None),
        ("missing-row", task(), [], [], True, "SYSTEM", False, "契约问题标题", None),
        ("unsafe-comparison", task(), [row(state="DIFFERENT")], [], True, "SYSTEM", False, "契约问题标题", None),
        ("red-unknown-code", task(reason=STATUS_ISSUE), [row()], [{"codes": ["UNKNOWN"], "status": "FAIL", "message": "未知证据失败"}], True, "SYSTEM", False, "红蓝发票关联检查", None),
        ("red-business-code", task(reason=STATUS_ISSUE), [row()], [{"codes": ["AMOUNT_CANCELLATION_MISMATCH"], "status": "FAIL", "message": "抵消关系待判断"}], True, "HUMAN", True, "红蓝发票关联检查", "请核对关联红票是否齐全"),
        ("red-no-code", task(reason=STATUS_ISSUE), [row()], [], True, "SYSTEM", False, "红蓝发票关联检查", None),
        ("bill-account", task("BILL_ACCOUNT", options=("confirm_bill_business",)), [row()], [], True, "HUMAN", True, "契约问题标题", "请查看已有确认及科目来源"),
        ("bill-opinion", task("BILL", options=("confirm_bill_business",)), [row(opinion="OPINION")], [], True, "HUMAN", True, "契约问题标题", "请查看已有意见"),
        ("bill-business", task(options=("confirm_bill_business",)), [row()], [], True, "HUMAN", True, "契约问题标题", "请确认实际业务性质"),
        ("statement-account", task(options=("confirm_statement_account",)), [row()], [], True, "HUMAN", True, "契约问题标题", "请确认这份流水"),
        ("business-period", task(reason="业务期间：其他月份", focus="transaction_date"), [row(field="transaction_date", value="2026-02-01")], [], True, "HUMAN", True, "契约问题标题", "请核对清单所列日期"),
        ("invoice-amount", task(options=("confirm_invoice_amount",)), [row()], [], True, "HUMAN", True, "契约问题标题", "请确认本条记录"),
        ("missing-invoice-date", task(reason="开票日期：为空", focus="invoice_date"), [row(field="invoice_date", state="MISSING", value=None)], [], True, "HUMAN", True, "契约问题标题", "请核对该发票原件"),
        ("verify", task("VERIFY", options=("verify_source_values",)), [row()], [], True, "HUMAN", True, "契约问题标题", "逐条查看原件与提取值"),
        ("unknown", task(), [row()], [], True, "SYSTEM", False, "契约问题标题", None),
    ],
)
def test_classify_task_characterization(
    name, value, rows, checks, source_valid, route, human_ready, title, question
):
    result = classify_task(value, rows, checks, source_valid)

    assert result["version"] == "issue-triage-v1", name
    assert result["route"] == route, name
    assert result["human_ready"] is human_ready, name
    assert result["title"] == title, name
    assert result["blocking_retained"] is True, name
    assert result["checks"] == checks, name
    if question:
        assert result["questions"] and question in result["questions"][0], name
        assert result["next_action"] == result["questions"][0], name
    else:
        assert result["questions"] == [], name
