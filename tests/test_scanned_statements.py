"""扫描件对账单：模型读出的数值必须被对账单自带的真值验过才算数。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.scanned_statements import (
    ScannedStatement, ScannedStatementError, data_url, horizontal_strips,
    parse_statement, read_and_verify, verify,
)

# 取自昆山荣鼎坤 2026-08 江苏银行对账单的真实首尾数字。
# 期初 101,017.78 − 借方 560,393.12 + 贷方 500,000.00 = 期末 40,624.66
OPENING = Decimal("101017.78")


def sample(rows=None, **totals_overrides):
    rows = rows if rows is not None else [
        {"sequence": 1, "transaction_date": "2026-08-03", "summary": "出差车费",
         "debit": "266.00", "balance": "100751.78", "counterparty_name": "侯文军"},
        {"sequence": 2, "transaction_date": "2026-08-03", "summary": "收费",
         "debit": "1.80", "balance": "100749.98"},
        {"sequence": 3, "transaction_date": "2026-08-12", "summary": "投资款",
         "credit": "100000.00", "balance": "200749.98", "counterparty_name": "陈彩萍"},
    ]
    totals = {"closing_balance": "200749.98", "debit_count": 2, "debit_total": "267.80",
              "credit_count": 1, "credit_total": "100000.00", "total_count": 3}
    totals.update(totals_overrides)
    return {"account_name": "昆山荣鼎坤机械科技有限公司", "account_number": "30430188000190758",
            "currency": "人民币", "period_start": "2026-08-01", "period_end": "2026-08-31",
            "totals": totals, "rows": rows}


# ---------- 结构 ----------

def test_a_well_read_statement_passes_every_check():
    report = verify(parse_statement(sample()))
    assert report.outcome == "ACCEPTED"
    assert [c.passed for c in report.checks] == [True] * 5 + [True]
    assert report.opening_balance == Decimal("101017.78")


def test_bank_direction_is_kept_as_printed():
    """银行视角借方是支出。读数阶段不做方向换算，免得一开始就把方向搞反。"""
    statement = parse_statement(sample())
    assert statement.rows[0].debit == Decimal("266.00") and statement.rows[0].credit == 0
    assert statement.rows[2].credit == Decimal("100000.00") and statement.rows[2].debit == 0


def test_money_accepts_thousands_separators_and_blank_placeholders():
    statement = parse_statement(sample(rows=[
        {"sequence": 1, "transaction_date": "2026-08-03", "debit": "1,266.00", "credit": "-",
         "balance": "99,751.78"}], closing_balance="99751.78", debit_count=1,
        debit_total="1266.00", credit_count=0, credit_total="0", total_count=1))
    assert statement.rows[0].debit == Decimal("1266.00")
    assert statement.rows[0].credit == Decimal("0.00")


def test_unreadable_amount_is_rejected_rather_than_guessed():
    with pytest.raises(ScannedStatementError, match="不符合约定结构"):
        parse_statement(sample(rows=[
            {"sequence": 1, "transaction_date": "2026-08-03", "debit": "2?6.00", "balance": "1"}]))


def test_non_iso_dates_are_rejected():
    with pytest.raises(ScannedStatementError):
        parse_statement(sample(rows=[
            {"sequence": 1, "transaction_date": "2026年8月3日", "debit": "1.00", "balance": "1"}]))


def test_unexpected_fields_are_rejected():
    payload = sample()
    payload["rows"][0]["confidence"] = 0.9
    with pytest.raises(ScannedStatementError):
        parse_statement(payload)


def test_a_statement_without_rows_is_rejected():
    with pytest.raises(ScannedStatementError):
        parse_statement(sample(rows=[]))


# ---------- 每一道校验都能独立抓错 ----------

def test_a_missed_row_is_caught_by_the_header_count():
    report = verify(parse_statement(sample(total_count=4)))
    assert report.outcome == "REVIEW"
    assert [c.name for c in report.failures][0] == "笔数与表头一致"


def test_a_misread_digit_breaks_balance_continuity():
    """把 1.80 读成 1.30：连续性、借方合计、期末余额会同时崩。"""
    rows = sample()["rows"]
    rows[1]["debit"] = "1.30"
    report = verify(parse_statement(sample(rows=rows)))
    assert report.outcome == "REVIEW"
    names = {c.name for c in report.failures}
    assert "行间余额连续" in names and "借方笔数与合计一致" in names


def test_a_swapped_direction_is_caught():
    rows = sample()["rows"]
    rows[2] = dict(rows[2]); rows[2].pop("credit"); rows[2]["debit"] = "100000.00"
    report = verify(parse_statement(sample(rows=rows)))
    assert report.outcome == "REVIEW"
    assert {"借方笔数与合计一致", "贷方笔数与合计一致"} <= {c.name for c in report.failures}


def test_a_wrong_closing_balance_is_caught():
    report = verify(parse_statement(sample(closing_balance="200749.99")))
    assert report.outcome == "REVIEW"
    assert "末行余额等于表头期末余额" in {c.name for c in report.failures}


def test_inconsistent_header_totals_are_caught_by_the_opening_derivation():
    report = verify(parse_statement(sample(debit_total="267.80", credit_total="100001.00",
                                           credit_count=1)))
    assert report.outcome == "REVIEW"
    assert "期初倒算与期末吻合" in {c.name for c in report.failures}


def test_every_check_reports_what_it_compared():
    for check in verify(parse_statement(sample())).checks:
        assert check.detail, f"{check.name} 没有说明比对了什么"


# ---------- 读取与重试 ----------

class FakeReader:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    def read(self, images, *, hint=""):
        images = list(images)
        self.calls.append({"images": len(images), "hint": hint})
        return self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]


def one_page_pdf() -> bytes:
    from io import BytesIO
    from PIL import Image
    from pypdf import PdfWriter, PageObject
    buffer = BytesIO()
    Image.new("RGB", (600, 900), "white").save(buffer, format="PNG")
    writer = PdfWriter()
    page = PageObject.create_blank_page(width=600, height=900)
    writer.add_page(page)
    out = BytesIO()
    writer.write(out)
    return out.getvalue(), buffer.getvalue()


def test_strips_overlap_so_a_row_on_the_seam_is_not_lost():
    _, image = one_page_pdf()
    strips = horizontal_strips(image, 3)
    assert len(strips) == 3
    from io import BytesIO
    from PIL import Image
    heights = [Image.open(BytesIO(s)).size[1] for s in strips]
    assert sum(heights) > 900, "切条之间必须有重叠"


def test_strip_count_is_capped():
    _, image = one_page_pdf()
    assert len(horizontal_strips(image, 99)) <= 6


def test_data_url_detects_the_real_image_type_not_the_extension():
    assert data_url(b"\x89PNG\r\n\x1a\n" + b"0" * 8).startswith("data:image/png;base64,")
    assert data_url(b"\xff\xd8\xff" + b"0" * 8).startswith("data:image/jpeg;base64,")


def test_reader_retries_with_strips_when_the_first_read_fails_verification(monkeypatch):
    import app.scanned_statements as module
    monkeypatch.setattr(module, "page_images", lambda content: [b"\x89PNG\r\n\x1a\n"])
    monkeypatch.setattr(module, "horizontal_strips", lambda image, count: [image] * count)
    bad = sample(total_count=4)
    reader = FakeReader(bad, sample())
    statement, report = read_and_verify(b"pdf", reader)
    assert report.outcome == "ACCEPTED"
    assert len(reader.calls) == 2
    assert "笔数与表头一致" in reader.calls[1]["hint"]


def test_a_good_first_read_is_not_retried(monkeypatch):
    import app.scanned_statements as module
    monkeypatch.setattr(module, "page_images", lambda content: [b"\x89PNG\r\n\x1a\n"])
    reader = FakeReader(sample())
    _, report = read_and_verify(b"pdf", reader)
    assert report.outcome == "ACCEPTED" and len(reader.calls) == 1


def test_two_failed_reads_return_the_better_one_for_human_review(monkeypatch):
    import app.scanned_statements as module
    monkeypatch.setattr(module, "page_images", lambda content: [b"\x89PNG\r\n\x1a\n"])
    monkeypatch.setattr(module, "horizontal_strips", lambda image, count: [image] * count)
    worse = sample(total_count=9, closing_balance="1.00", debit_total="9.99")
    better = sample(total_count=4)
    statement, report = read_and_verify(b"pdf", FakeReader(worse, better))
    assert report.outcome == "REVIEW"
    assert len(report.failures) == 1, "应当交回失败更少的那一份"


# ---------- 真实扫描件 ----------

REAL = "/Users/starryn/dev/finwise/.data/荣鼎坤/江苏银行对公账户对本账单供参考.pdf"


@pytest.mark.skipif(not __import__("pathlib").Path(REAL).exists(), reason="需要本地语料")
def test_real_scanned_statement_is_recognised_as_image_only():
    from pathlib import Path
    from app.scanned_statements import is_image_only_pdf, page_images
    content = Path(REAL).read_bytes()
    assert is_image_only_pdf(content)
    images = page_images(content)
    assert len(images) == 2
    assert all(len(image) > 10_000 for image in images)


@pytest.mark.skipif(not __import__("pathlib").Path(REAL).exists(), reason="需要本地语料")
def test_real_scanned_statement_does_not_hard_fail_the_import():
    """扫描件进来不算解析失败，只是标明需要图像识别。"""
    from pathlib import Path
    from app.tabular import ParseOptions, extract_workbook
    result = extract_workbook(Path(REAL).read_bytes(),
                              ParseOptions(document_kind="bank_statement"), "2026-08")
    assert result["records"] == [] and result["errors"] == []
    assert result["sheets"][0]["status"] == "SCANNED_IMAGE"


def test_a_corrupt_pdf_still_fails_explicitly():
    from app.scanned_statements import is_image_only_pdf
    assert is_image_only_pdf(b"%PDF-unknown") is False
