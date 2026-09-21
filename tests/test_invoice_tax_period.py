"""进项发票的期间归属取税款所属期，不取开票日期。

税局导出的发票清单在表头写明税款所属期。7 月开具的差旅票在 8 月勾选抵扣
是常规业务，按开票日期判期间会把它们全部报成"期间异常"——性质说错了，
而且会把真正的期间问题淹没在噪声里。
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

from app.tabular import ParseOptions, extract_workbook
from test_tabular_ingestion import xlsx_fixture

HEADER = ["数电发票号码", "开票日期", "金额", "税额", "价税合计", "销售方纳税人名称"]


def invoices(rows, tax_period="2026年08月", period="2026-08"):
    sheet = [[f"税款所属期 {tax_period}"], HEADER] + rows if tax_period else [HEADER] + rows
    return extract_workbook(xlsx_fixture([("发票", sheet)]),
                            ParseOptions(document_kind="purchase_invoices"), period)


IN_PERIOD = ["2600001", "2026-08-08", "100.00", "13.00", "113.00", "某供应商"]
EARLIER = ["2600002", "2026-07-30", "200.00", "26.00", "226.00", "某车站"]


def test_an_invoice_inside_the_tax_period_passes_cleanly():
    record = invoices([IN_PERIOD])["records"][0]
    assert record["period_check"] == "PASS"
    assert record["extraction_issues"] == []
    assert record["normalized_value"]["period"] == "2026-08"


def test_an_earlier_invoice_deducted_this_period_is_attributed_here():
    """归属期跟随勾选所属期，但开票日期原样保留 —— 那是原件上的事实。"""
    record = invoices([EARLIER])["records"][0]
    assert record["period_check"] == "PASS"
    assert record["normalized_value"]["period"] == "2026-08"
    assert record["normalized_value"]["invoice_date"] == "2026-07-30"


def test_the_cross_period_deduction_is_stated_not_silently_accepted():
    """跨期抵扣要会计判断费用归属，不能因为期间对上就不吭声。"""
    record = invoices([EARLIER])["records"][0]
    assert any("跨期抵扣" in issue and "费用归属期间" in issue
               for issue in record["extraction_issues"])
    assert record["extraction_confidence"] == 0.0


def test_a_sheet_without_a_tax_period_still_falls_back_to_the_invoice_date():
    record = invoices([EARLIER], tax_period=None)["records"][0]
    assert record["period_check"] == "PERIOD_EXCEPTION"


def test_a_tax_period_outside_the_accounting_period_is_still_an_exception():
    """所属期本身就不是当期时，仍然是真正的期间异常。"""
    record = invoices([IN_PERIOD], tax_period="2026年07月", period="2026-08")["records"][0]
    assert record["period_check"] == "PERIOD_EXCEPTION"


REAL = glob.glob("/Users/starryn/dev/finwise/.data/荣鼎坤/*8月进项*")


@pytest.mark.skipif(not REAL, reason="需要本地语料")
def test_the_real_august_purchase_list_has_no_period_exception():
    """真实语料里 27 张进项有 7 张是 7 月开票、8 月勾选的差旅票。"""
    result = extract_workbook(Path(REAL[0]).read_bytes(),
                              ParseOptions(document_kind="purchase_invoices"), "2026-08")
    records = result["records"]
    assert len(records) == 27
    assert [r for r in records if r["period_check"] != "PASS"] == []
    crossed = [r for r in records if any("跨期抵扣" in i for i in r["extraction_issues"])]
    assert len(crossed) == 7
    assert all(r["normalized_value"]["invoice_date"].startswith("2026-07") for r in crossed)
