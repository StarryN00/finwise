"""价税合计由已核对的净额与税额算出时，不该报"无法验证"。

税局的进项清单只有金额与税额两列，没有价税合计。系统由两者相加得出，
此时它没有独立来源可比 —— 但正确性由输入保证：净额与税额都已逐笔加总
核对无误，且每一条的价税合计确实等于两者之和。
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

from app.reconcile import reconcile


def record(row, net, tax, derived=True, total=None):
    value = {"net_amount": net, "tax": tax, "invoice_total": total or f"{float(net) + float(tax):.2f}"}
    if derived:
        value["invoice_total_derivation"] = "net_amount + tax"
    sources = {"net_amount": {"region": f"发票!K{row}"}, "tax": {"region": f"发票!L{row}"}}
    if not derived:
        sources["invoice_total"] = {"region": f"发票!M{row}"}
    return {"record_type": "INVOICE", "source_anchor": {"row": row},
            "normalized_value": value, "field_sources": sources,
            "original_value": {"sheet": "发票", "row": row}, "extraction_issues": []}


def extracted(records, totals, total_column=None):
    """totals 是原件自报的整表合计行，按真实文件的形态放在 K、L 两列。"""
    values = [""] * 13
    values[0] = "合计"
    values[10], values[11] = totals[0], totals[1]   # K、L
    if total_column is not None:
        values[12] = total_column                    # M
    return {"records": records,
            "sheets": [{"sheet": "发票", "status": "EXTRACTED", "rows": len(records),
                        "header_row": 1,
                        "reference_rows": [{"row": 99, "reason": "SUMMARY_REFERENCE",
                                            "values": values}]}],
            "errors": []}


def codes(result):
    return {item["code"]: item["status"] for item in result["items"]}


def test_a_derived_total_is_verified_through_its_verified_inputs():
    result = reconcile(extracted([record(2, "100.00", "13.00"), record(3, "200.00", "26.00")],
                                 ("300.00", "39.00")), "purchase_invoices")
    assert codes(result)["INVOICE_TOTAL_INVOICE_TOTAL"] == "MATCH"
    assert result["overall"] == "MATCH"
    message = next(i["message"] for i in result["items"]
                   if i["code"] == "INVOICE_TOTAL_INVOICE_TOTAL")
    assert "原件无此列" in message and "2 条记录逐条相加相符" in message


def test_a_row_where_the_total_does_not_equal_its_parts_is_not_let_through():
    """任何一条对不上就退回"无法验证"，不放宽。"""
    bad = record(3, "200.00", "26.00", total="225.00")
    result = reconcile(extracted([record(2, "100.00", "13.00"), bad], ("300.00", "39.00")),
                       "purchase_invoices")
    assert codes(result)["INVOICE_TOTAL_INVOICE_TOTAL"] == "NOT_AVAILABLE"


def test_unverified_inputs_do_not_confer_verification():
    """净额合计对不上时，由它算出的价税合计当然也不算核对过。"""
    result = reconcile(extracted([record(2, "100.00", "13.00")], ("999.00", "13.00")),
                       "purchase_invoices")
    assert codes(result)["INVOICE_TOTAL_NET_AMOUNT"] == "MISMATCH"
    assert codes(result)["INVOICE_TOTAL_INVOICE_TOTAL"] == "NOT_AVAILABLE"


def test_a_total_that_exists_in_the_source_is_checked_on_its_own_merits():
    """原件里确有价税合计列时，走的是原来的独立核对，不是派生推定。"""
    result = reconcile(extracted([record(2, "100.00", "13.00", derived=False)],
                                 ("100.00", "13.00"), total_column="113.00"),
                       "purchase_invoices")
    message = next(i["message"] for i in result["items"]
                   if i["code"] == "INVOICE_TOTAL_INVOICE_TOTAL")
    assert codes(result)["INVOICE_TOTAL_INVOICE_TOTAL"] == "MATCH"
    assert "原件无此列" not in message, "有来源列时不该走派生推定"
    assert "全表价税合计声明" in message


def test_a_source_total_that_disagrees_is_still_caught():
    """有来源列但对不上时，绝不能被派生规则救回来。"""
    result = reconcile(extracted([record(2, "100.00", "13.00", derived=False)],
                                 ("100.00", "13.00"), total_column="999.00"),
                       "purchase_invoices")
    assert codes(result)["INVOICE_TOTAL_INVOICE_TOTAL"] == "MISMATCH"


REAL = glob.glob("/Users/starryn/dev/finwise/.data/荣鼎坤/*8月进项*")


@pytest.mark.skipif(not REAL, reason="需要本地语料")
def test_the_real_purchase_list_now_reconciles(monkeypatch):
    from app.tabular import ParseOptions, extract_workbook
    result = extract_workbook(Path(REAL[0]).read_bytes(),
                              ParseOptions(document_kind="purchase_invoices"), "2026-08")
    checks = result["checks"]
    assert checks["overall"] == "MATCH"
    assert {i["status"] for i in checks["items"]
            if i["code"].startswith("INVOICE_TOTAL_")} == {"MATCH"}
