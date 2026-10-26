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
    assert report.failures == []
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


def test_an_out_of_period_date_is_caught():
    """真实样本里有一笔 2026-09-03 出现在 8 月对账单中 —— 银行数据本身的异常，
    但操作人必须看到它，不能默默入账。"""
    rows = sample()["rows"]
    rows[1] = dict(rows[1], transaction_date="2026-09-03")
    report = verify(parse_statement(sample(rows=rows)))
    assert report.outcome == "REVIEW"
    assert "日期落在对账单期间内" in {c.name for c in report.failures}


def test_a_date_that_goes_backwards_is_caught_even_inside_the_period():
    """模型把 2026-09-03 读成了 2026-08-02：落在期间内，六道数字校验全过，
    只有时序倒退能抓住它。"""
    rows = sample()["rows"]
    rows[1] = dict(rows[1], transaction_date="2026-08-02")
    report = verify(parse_statement(sample(rows=rows)))
    assert report.outcome == "REVIEW"
    failures = {c.name for c in report.failures}
    assert failures == {"日期随序号不倒退"}, "数字校验应当全过，只有时序能发现这个错"


def test_text_fields_are_declared_unverified():
    """摘要没有任何算术约束，读错不会被任何一道校验抓到，必须一路标到人工确认。"""
    report = verify(parse_statement(sample()))
    assert "summary" in report.unverified_fields
    assert "counterparty_name" in report.unverified_fields


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


# ---------- 多次读取取共识 ----------

def test_majority_wins_and_the_minority_is_still_reported():
    """三次里两次一致：采用多数值，但仍然如实记下有过分歧。"""
    from app.scanned_statements import consensus
    good = parse_statement(sample())
    typo = sample()
    typo["rows"][1]["debit"] = "1.30"
    merged, disputed = consensus([good, parse_statement(typo), good])
    assert merged.rows[1].debit == Decimal("1.80")
    assert [(d.sequence, d.field) for d in disputed] == [(2, "debit")]
    assert sorted(disputed[0].values) == ["1.30", "1.80"]


def test_a_field_that_never_agrees_is_disputed():
    """真实样本第 9 行被印章遮挡，三次读出三个日期 —— 没有多数可言。"""
    from app.scanned_statements import consensus
    variants = []
    for date in ("2026-08-02", "2026-08-03", "2026-09-02"):
        payload = sample()
        payload["rows"][0]["transaction_date"] = date
        variants.append(parse_statement(payload))
    _, disputed = consensus(variants)
    dates = [d for d in disputed if d.field == "transaction_date"]
    assert len(dates) == 1 and len(dates[0].values) == 3


def test_a_row_missing_from_some_rounds_is_flagged():
    from app.scanned_statements import consensus
    full = parse_statement(sample())
    short = sample()
    short["rows"] = short["rows"][:2]
    _, disputed = consensus([full, parse_statement(short), full])
    assert any(d.field == "行存在性" and d.sequence == 3 for d in disputed)


def test_single_round_needs_no_consensus():
    from app.scanned_statements import consensus
    only = parse_statement(sample())
    merged, disputed = consensus([only])
    assert merged is only and disputed == []


def test_consensus_read_rejects_when_numbers_or_dates_disagree(monkeypatch):
    import app.scanned_statements as module
    from app.scanned_statements import read_with_consensus
    monkeypatch.setattr(module, "page_images", lambda content: [b"\x89PNG\r\n\x1a\n"])
    typo = sample()
    typo["rows"][1]["debit"] = "1.30"
    reader = FakeReader(sample(), typo, sample())
    _, report = read_with_consensus(b"pdf", reader, rounds=3)
    assert report.outcome == "REVIEW"
    assert "多次读取金额与日期一致" in {c.name for c in report.failures}
    assert report.rounds == 3


def test_consensus_read_accepts_when_every_round_agrees(monkeypatch):
    import app.scanned_statements as module
    from app.scanned_statements import read_with_consensus
    monkeypatch.setattr(module, "page_images", lambda content: [b"\x89PNG\r\n\x1a\n"])
    _, report = read_with_consensus(b"pdf", FakeReader(sample()), rounds=3)
    assert report.outcome == "ACCEPTED" and report.disputed == []


def test_text_disagreement_alone_does_not_block_but_is_recorded(monkeypatch):
    """对方户名的形近字每次都不同，不该因此卡住整份对账单，但必须留痕待人工核对。"""
    import app.scanned_statements as module
    from app.scanned_statements import read_with_consensus
    monkeypatch.setattr(module, "page_images", lambda content: [b"\x89PNG\r\n\x1a\n"])
    variant = sample()
    variant["rows"][0]["counterparty_name"] = "候文军"
    reader = FakeReader(sample(), variant, sample())
    _, report = read_with_consensus(b"pdf", reader, rounds=3)
    assert report.outcome == "ACCEPTED"
    assert any(d.field == "counterparty_name" for d in report.disputed)


def test_all_rounds_failing_raises_rather_than_returning_nothing(monkeypatch):
    import app.scanned_statements as module
    from app.scanned_statements import ScannedStatementError, read_with_consensus
    monkeypatch.setattr(module, "page_images", lambda content: [b"\x89PNG\r\n\x1a\n"])
    with pytest.raises(ScannedStatementError):
        read_with_consensus(b"pdf", FakeReader({"totals": {}, "rows": []}), rounds=2)


# ---------- 转成事实记录 ----------

def records_for(statement_payload=None, **kw):
    from app.scanned_statements import to_records
    statement = parse_statement(statement_payload or sample())
    report = verify(statement)
    return to_records(statement, report, period=kw.pop("period", "2026-08"), **kw)


def test_records_match_the_shape_the_table_path_produces():
    record = records_for(bank_account="ACCT-1")[0]
    assert set(record) >= {"record_type", "source_anchor", "original_value", "normalized_value",
                           "field_sources", "extraction_issues", "extraction_confidence", "period_check"}
    assert record["source_anchor"]["row"] == 1


def test_bank_debit_becomes_expense_in_book_terms():
    """银行视角的借方是账户支出。换算只在这一步做一次，读数阶段不碰方向。"""
    records = records_for(bank_account="ACCT-1")
    assert records[0]["record_type"] == "PAYMENT"
    assert records[0]["normalized_value"]["expense"] == "266.00"
    assert records[0]["normalized_value"]["income"] == "0.00"
    assert records[2]["record_type"] == "RECEIPT"
    assert records[2]["normalized_value"]["income"] == "100000.00"


def test_a_clean_row_never_reaches_full_confidence():
    """扫描件读数不该拿到和单元格一样的信心：摘要与对方从未被校验过。"""
    record = records_for(bank_account="ACCT-1")[0]
    assert record["extraction_issues"] == []
    assert 0 < record["extraction_confidence"] < 1


def test_a_disputed_amount_becomes_a_row_level_issue():
    from app.scanned_statements import DisputedField, to_records
    statement = parse_statement(sample())
    report = verify(statement)
    report.disputed.append(DisputedField(sequence=1, field="debit", values=["266.00", "266.90"]))
    record = to_records(statement, report, period="2026-08", bank_account="ACCT-1")[0]
    assert any("多次识别结果不一致" in issue for issue in record["extraction_issues"])
    assert record["extraction_confidence"] == 0.0


def test_a_disputed_name_is_recorded_with_softer_wording():
    from app.scanned_statements import DisputedField, to_records
    statement = parse_statement(sample())
    report = verify(statement)
    report.disputed.append(DisputedField(sequence=1, field="counterparty_name", values=["侯文军", "候文军"]))
    record = to_records(statement, report, period="2026-08", bank_account="ACCT-1")[0]
    assert any("识别结果不稳定" in issue for issue in record["extraction_issues"])


def test_verified_fields_exclude_whatever_was_disputed():
    from app.scanned_statements import DisputedField, to_records
    statement = parse_statement(sample())
    report = verify(statement)
    report.disputed.append(DisputedField(sequence=1, field="transaction_date", values=["a", "b"]))
    record = to_records(statement, report, period="2026-08", bank_account="ACCT-1")[0]
    assert "transaction_date" not in record["verified_fields"]
    assert "expense" in record["verified_fields"]


def test_a_row_outside_the_period_is_marked():
    rows = sample()["rows"]
    rows[0] = dict(rows[0], transaction_date="2026-09-03")
    records = records_for(sample(rows=rows), bank_account="ACCT-1", period="2026-08")
    assert records[0]["period_check"] == "PERIOD_EXCEPTION"


def test_missing_bank_account_is_still_an_issue():
    assert any("bank_account_ref" in issue for issue in records_for()[0]["extraction_issues"])


def test_account_numbers_ignore_line_wrap_spaces():
    """账号在扫描件里折行，模型有时把换行读成空格。同一个账号不该因此被判成分歧。"""
    from app.scanned_statements import consensus
    a = sample(); a["rows"][0]["counterparty_account"] = "6217732000504 146"
    b = sample(); b["rows"][0]["counterparty_account"] = "6217732000504146"
    merged, disputed = consensus([parse_statement(a), parse_statement(b)])
    assert merged.rows[0].counterparty_account == "6217732000504146"
    assert [d for d in disputed if d.field == "counterparty_account"] == []


def test_text_fields_also_ignore_stray_whitespace():
    from app.scanned_statements import consensus
    a = sample(); a["rows"][0]["counterparty_name"] = "侯 文军"
    b = sample(); b["rows"][0]["counterparty_name"] = "侯文军"
    _, disputed = consensus([parse_statement(a), parse_statement(b)])
    assert [d for d in disputed if d.field == "counterparty_name"] == []


def test_a_genuinely_different_account_is_still_disputed():
    from app.scanned_statements import consensus
    a = sample(); a["rows"][0]["counterparty_account"] = "6217732000504146"
    b = sample(); b["rows"][0]["counterparty_account"] = "6217732000504147"
    _, disputed = consensus([parse_statement(a), parse_statement(b)])
    assert len([d for d in disputed if d.field == "counterparty_account"]) == 1


def test_a_failed_scan_keeps_its_reason_where_the_operator_can_see_it(client, scope):
    """识别没跑成时只显示"识别失败"没有意义 —— 人无从知道是没配模型、
    超时还是校验没过，也就无从决定下一步。"""
    import base64
    from pathlib import Path as _Path
    if not _Path(REAL).exists():
        import pytest as _pytest
        _pytest.skip("需要本地语料")
    headers = {"X-Actor-Id": "alice", "X-Role": "accountant"}
    client.post("/api/v1/scopes", headers=headers, json=scope)
    uploaded = client.post("/api/v1/artifacts", headers=headers, json={
        "scope": scope, "filename": "对账单.pdf",
        "content_base64": base64.b64encode(_Path(REAL).read_bytes()).decode(),
        "observed_period": scope["accounting_period_id"]}).json()
    response = client.post("/api/v1/commands", headers=headers, json={
        "action": "parse_artifact", "target_id": uploaded["object_id"],
        "target_version": uploaded["version"], "scope": scope,
        "idempotency_key": "scan-reason-0001",
        "payload": {"document_kind": "bank_statement"}})
    assert response.status_code == 200, response.text
    artifact = response.json()["effect"]["artifact"]
    # 测试环境没有启用网关，因此必然走不通 —— 关键是它要说出来。
    assert artifact["data"]["parse_errors"], "识别未完成时必须留下原因"
    assert "扫描件" in artifact["data"]["parse_errors"][0]
