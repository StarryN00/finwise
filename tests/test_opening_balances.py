"""余额表 → 基线确认。结构取自昆山荣鼎坤 202607 的真实导出。"""
from __future__ import annotations

import glob
from decimal import Decimal
from pathlib import Path

import pytest

from app.opening_balances import (
    OpeningBalanceError, leaves, parse_balance_sheet, to_confirmation, trial_balance,
)
from app.tabular import read_workbook
from test_tabular_ingestion import xlsx_fixture

TOP = ["序号", "科目编码", "科目", "期初余额", None, "本期发生额", None, "期末余额", None]
SUB = [None, None, None, "借方金额", "贷方金额", "借方金额", "贷方金额", "借方金额", "贷方金额"]


def line(seq, code, name, debit="", credit=""):
    return [seq, code, name, "", "", "", "", debit, credit]


def sheet(rows):
    return read_workbook(xlsx_fixture([("Sheet1", [["余额表"], ["账套名称:测试"], ["期间:202601至202607"],
                                                   TOP, SUB] + rows)]))[0]


REAL = glob.glob("/Users/starryn/dev/finwise/.data/荣鼎坤/*余额表_202601_202607*.xlsx")


# ---------- 层级 ----------

def test_multi_level_accounts_keep_only_leaves():
    """2221 → 222101 → 22210101。中间层是汇总，连同末级一起加会重复计数。"""
    roots = parse_balance_sheet(sheet([
        line(1, "2221", "应交税费", "64155.51"),
        line(2, "222101", "应交增值税", "67047.00"),
        line(3, "22210101", "进项税额", "151064.52"),
        line(4, "22210107", "销项税额", "", "116424.78"),
        line(5, "22210104", "转出未交增值税", "32407.26"),
        line(6, "222121", "应交个人所得税", "", "2891.49"),
    ]))
    assert [r.account_code for r in roots] == ["2221"]
    codes = [leaf.account_code for leaf in leaves(roots[0])]
    assert codes == ["22210101", "22210107", "22210104", "222121"]
    assert sum(leaf.net for leaf in leaves(roots[0])) == roots[0].net == Decimal("64155.51")


def test_a_leaf_at_top_level_is_its_own_leaf():
    roots = parse_balance_sheet(sheet([line(1, "1001", "库存现金", "500.00")]))
    assert [leaf.account_code for leaf in leaves(roots[0])] == ["1001"]


def test_rows_without_an_account_code_are_skipped():
    roots = parse_balance_sheet(sheet([
        line(1, "1001", "库存现金", "500.00"), ["", "", "本页合计", "", "", "", "", "500.00", ""]]))
    assert len(roots) == 1


def test_missing_header_is_reported_not_guessed():
    with pytest.raises(OpeningBalanceError, match="定位表头"):
        parse_balance_sheet(read_workbook(xlsx_fixture([("S", [["随便一张表"], ["a", "b"]])]))[0])


def test_an_empty_balance_sheet_is_rejected():
    with pytest.raises(OpeningBalanceError, match="没有读到任何科目"):
        parse_balance_sheet(sheet([["", "", "合计", "", "", "", "", "", ""]]))


def test_an_unreadable_amount_is_rejected_rather_than_zeroed():
    with pytest.raises(OpeningBalanceError, match="余额无法识别"):
        parse_balance_sheet(sheet([line(1, "1001", "库存现金", "五百元")]))


def test_thousands_separators_and_dashes_are_handled():
    roots = parse_balance_sheet(sheet([line(1, "1002", "银行存款", "1,101,017.78", "-")]))
    assert roots[0].closing_debit == Decimal("1101017.78")
    assert roots[0].closing_credit == Decimal("0.00")


# ---------- 转基线 ----------

def source(row=1):
    return {"artifact_id": "art-1", "version": 1, "anchor": {"row": row, "region": "余额表!1"}}


def confirmation(rows, **kw):
    roots = parse_balance_sheet(sheet(rows))
    return to_confirmation(roots, prior_period=kw.pop("prior_period", "2026-07"),
                           close_reference="余额表 202601至202607",
                           balance_source=source(), close_source=source(), **kw)


BALANCED = [line(1, "1002", "银行存款", "101017.78"), line(2, "3001", "实收资本", "", "101017.78")]


def test_an_unbalanced_sheet_is_refused_without_adjustment():
    """借贷不平就直接拒绝。基线是往后所有账的起点，不能修饰。"""
    with pytest.raises(OpeningBalanceError, match="试算不平衡"):
        confirmation([line(1, "1002", "银行存款", "101017.78"),
                      line(2, "3001", "实收资本", "", "101000.00")])


def test_every_balance_points_back_to_a_row_in_the_source():
    payload = confirmation(BALANCED)
    assert all(item["source_anchor"]["row"] for item in payload["balances"])


def test_opening_equals_closing_because_a_baseline_carries_the_prior_close():
    item = confirmation(BALANCED)["balances"][0]
    assert item["opening_debit"] == item["closing_debit"] == "101017.78"


def test_current_account_details_become_auxiliary_entries():
    payload = confirmation([
        line(1, "2202", "应付账款", "", "199094.68"),
        line(2, "220201", "甲供应商", "", "249386.78"),
        line(3, "220202", "乙供应商", "50292.10"),
        line(4, "1002", "银行存款", "199094.68"),
    ])
    payable = next(b for b in payload["balances"] if b["account_code"] == "2202")
    assert payable["requires_auxiliary"] is True
    assert [a["key"] for a in payable["auxiliary"]] == ["甲供应商", "乙供应商"]
    # 明细各自的方向必须保留，它们是往来核销的依据。
    assert payable["auxiliary"][0]["closing_credit"] == "249386.78"
    assert payable["auxiliary"][1]["closing_debit"] == "50292.10"


def test_a_non_current_account_with_children_needs_no_auxiliary():
    payload = confirmation([
        line(1, "1002", "银行存款", "101017.78"),
        line(2, "100201", "江苏银行0758", "101017.78"),
        line(3, "3001", "实收资本", "", "101017.78"),
    ])
    bank = next(b for b in payload["balances"] if b["account_code"] == "1002")
    assert bank["requires_auxiliary"] is False and bank["auxiliary"] == []


def test_the_payload_passes_the_baseline_contract():
    from app.ontology.baseline import BaselineConfirmation
    confirmed = BaselineConfirmation.model_validate(confirmation(BALANCED))
    assert sum(b.opening_debit - b.opening_credit for b in confirmed.balances) == 0


# ---------- 真实余额表 ----------

@pytest.mark.skipif(not REAL, reason="需要本地语料")
def test_the_real_july_sheet_produces_a_valid_baseline():
    from app.ontology.baseline import BaselineConfirmation
    roots = parse_balance_sheet(read_workbook(Path(REAL[0]).read_bytes())[0])
    debit, credit = trial_balance(roots)
    assert debit == credit == Decimal("1142245.37")

    payload = to_confirmation(roots, prior_period="2026-07",
                              close_reference="余额表 202601至202607",
                              balance_source=source(), close_source=source())
    confirmed = BaselineConfirmation.model_validate(payload)
    assert len(confirmed.balances) == 22
    assert sum(b.opening_debit - b.opening_credit for b in confirmed.balances) == 0


@pytest.mark.skipif(not REAL, reason="需要本地语料")
def test_the_real_opening_bank_balance_matches_the_august_statement():
    """202607 期末 = 8 月对账单倒算出的期初。基线与当月流水必须在这一点接上。"""
    roots = parse_balance_sheet(read_workbook(Path(REAL[0]).read_bytes())[0])
    bank = next(r for r in roots if r.account_code == "1002")
    assert bank.closing_debit == Decimal("101017.78")


@pytest.mark.skipif(not REAL, reason="需要本地语料")
def test_the_real_current_accounts_reconcile_by_net():
    """应付账款控制科目按净额列示，33 个供应商里借贷双向都有。"""
    roots = parse_balance_sheet(read_workbook(Path(REAL[0]).read_bytes())[0])
    payable = next(r for r in roots if r.account_code == "2202")
    detail = leaves(payable)
    assert len(detail) == 33
    assert any(d.closing_debit > 0 for d in detail) and any(d.closing_credit > 0 for d in detail)
    assert sum(d.net for d in detail) == payable.net
