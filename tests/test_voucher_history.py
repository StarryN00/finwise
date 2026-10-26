"""从账套已有凭证里学做账习惯。结构取自昆山荣鼎坤 202601~202608 的真实序时账。"""
from __future__ import annotations

import glob
from decimal import Decimal
from pathlib import Path

import pytest

from app.tabular import read_workbook
from app.voucher_history import (
    JournalError, account_vocabulary, learn_expense_rules, learn_templates,
    match_account, normalize_party, parse_journal,
)
from test_tabular_ingestion import xlsx_fixture

HEAD = ["序号", "科目编码", "科目", "日期", "凭证号", "摘要", "数量", "计量单位", "币种", "原币金额", "借方", "贷方"]


def row(seq, code, name, day, number, summary, debit="0", credit="0"):
    return [seq, code, name, day, number, summary, "0", "", "", "0", debit, credit]


def journal(rows):
    return read_workbook(xlsx_fixture([("序时账", [["序时账"], ["账套名称:测试"],
                                                   ["期间:202601至202608"], HEAD] + rows)]))[0]


# 报销：借费用 / 贷个人；再借个人 / 贷银行 —— 代账公司的实际习惯
REIMBURSE = [
    row(1, "560202", "办公费", "2026-07-31", "记-001", "报销", debit="91.53"),
    row(2, "224101", "侯文军", "2026-07-31", "记-001", "报销", credit="91.53"),
    row(3, "224101", "侯文军", "2026-07-31", "记-001", "报销", debit="91.53"),
    row(4, "100201", "江苏银行0758", "2026-07-31", "记-001", "报销", credit="91.53"),
]
# 采购挂账：没有银行行，但"这个供应商走原材料"的习惯就在这里
ACCRUAL = [
    row(5, "1403", "原材料", "2026-07-31", "记-002", "采购原材料", debit="336.28"),
    row(6, "22210101", "进项税额", "2026-07-31", "记-002", "采购原材料", debit="43.72"),
    row(7, "220217", "山东高精橡塑制品有限公司", "2026-07-31", "记-002", "采购原材料", credit="380.00"),
]


# ---------- 解析 ----------

def test_lines_group_into_vouchers_by_number_and_period():
    vouchers = parse_journal(journal(REIMBURSE + ACCRUAL))
    assert {v.number for v in vouchers} == {"记-001", "记-002"}
    assert all(v.balanced() for v in vouchers)


def test_bank_direction_comes_from_the_bank_line():
    voucher = next(v for v in parse_journal(journal(REIMBURSE)) if v.number == "记-001")
    assert voucher.bank_driven and voucher.direction == "PAYMENT"
    assert voucher.bank_total == Decimal("91.53")


def test_a_voucher_without_a_bank_line_is_not_bank_driven():
    voucher = next(v for v in parse_journal(journal(ACCRUAL)) if v.number == "记-002")
    assert not voucher.bank_driven and voucher.direction is None


def test_rows_without_a_date_or_number_are_skipped():
    rows = REIMBURSE + [row(9, "1001", "库存现金", "", "", "本月合计", debit="1")]
    assert len(parse_journal(journal(rows))) == 1


def test_a_sheet_without_the_expected_header_is_reported():
    with pytest.raises(JournalError, match="定位表头"):
        parse_journal(read_workbook(xlsx_fixture([("S", [["随便"], ["a", "b"]])]))[0])


# ---------- 模板 ----------

def test_a_settled_party_yields_a_template_with_the_transit_account():
    templates = learn_templates(parse_journal(journal(REIMBURSE)))
    template = templates[(normalize_party("侯文军"), "PAYMENT")]
    assert template.party_account == "224101"
    assert template.via_party is True and template.settlements == 1
    assert template.expense_accounts[0] == ("560202", "办公费")


def test_an_accrual_only_party_is_still_learned_but_marked_unsettled():
    """只挂过账没付过款的对象，科目习惯可信，结算结构未知。"""
    templates = learn_templates(parse_journal(journal(ACCRUAL)))
    template = templates[(normalize_party("山东高精橡塑制品有限公司"), "PAYMENT")]
    assert template.settlements == 0 and template.via_party is False
    assert template.splits_input_tax is True
    assert template.expense_accounts[0] == ("1403", "原材料")


def test_party_names_are_normalized_so_punctuation_does_not_split_them():
    assert normalize_party("亚德客（江苏）自动化有限公司") == normalize_party("亚德客(江苏)自动化有限公司")


# ---------- 摘要与科目 ----------

def test_an_exact_historical_wording_maps_to_the_account_it_was_recorded_as():
    vouchers = parse_journal(journal(REIMBURSE))
    rules = learn_expense_rules(vouchers)
    found, why = match_account("报销", rules, account_vocabulary(vouchers))
    assert found.account_code == "560202" and "记过" in why


def test_an_unseen_wording_abstains_instead_of_guessing_the_common_account():
    """实测按字面重合去猜是负面结果：14 个真实摘要对 0 错 4。
    "出差车费"因"车费"被判成汽车费，"7月手机宽带费"因"7月"撞上"计提7月折旧"
    被判成固定资产折旧。宁可不给答案，也不要一条不会报错的错账。"""
    vouchers = parse_journal(journal(REIMBURSE))
    found, why = match_account("购买水果礼盒", learn_expense_rules(vouchers),
                               account_vocabulary(vouchers))
    assert found is None and "需要按科目含义判断" in why


def test_an_empty_summary_abstains():
    found, why = match_account("", [], [])
    assert found is None and "没有摘要" in why


def test_the_vocabulary_excludes_bank_party_and_tax_lines():
    """在用科目表只收"记什么"的行：银行、往来、进项税都不是费用科目。"""
    codes = {rule.account_code for rule in account_vocabulary(parse_journal(journal(REIMBURSE + ACCRUAL)))}
    assert codes == {"560202", "1403"}


# ---------- 真实序时账 ----------

REAL = glob.glob("/Users/starryn/dev/finwise/.data/荣鼎坤/*序时账*")


@pytest.mark.skipif(not REAL, reason="需要本地语料")
def test_the_real_journal_parses_and_balances():
    vouchers = parse_journal(read_workbook(Path(REAL[0]).read_bytes())[0])
    assert len(vouchers) == 241
    assert all(v.balanced() for v in vouchers)
    assert sum(1 for v in vouchers if v.bank_driven) == 137


@pytest.mark.skipif(not REAL, reason="需要本地语料")
def test_seven_months_of_history_covers_most_of_the_held_out_month():
    """1~7 月学、8 月验。未命中的应当是当月新出现的往来对象，那本就该问人。"""
    from app.voucher_history import _counterpart
    vouchers = parse_journal(read_workbook(Path(REAL[0]).read_bytes())[0])
    templates = learn_templates([v for v in vouchers if v.period < "2026-08"])
    august = [v for v in vouchers if v.period == "2026-08" and v.bank_driven and v.balanced()]
    assert len(august) == 30
    hits = 0
    for voucher in august:
        party = _counterpart(voucher)
        if party and (normalize_party(party.account_name), voucher.direction) in templates:
            hits += 1
    assert hits >= 22, f"留出月份命中 {hits}/30，低于已验证水平"
