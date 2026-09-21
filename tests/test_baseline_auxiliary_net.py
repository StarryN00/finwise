"""辅助核算明细与控制科目的比对口径。

取自昆山荣鼎坤 202607 余额表的真实形态：应付账款控制科目贷方 199,094.68，
其下 35 个供应商里既有应付的贷方余额，也有预付的借方余额。账套把控制科目
轧成净额，明细保持各自方向 —— 这是完全正常的账，不能判成不一致。
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.ontology.baseline import AccountBalance

ANCHOR = {"row": 7}


def payable(auxiliary, *, closing_debit="0.00", closing_credit="199094.68"):
    return {
        "account_code": "2202", "account_name": "应付账款",
        "closing_debit": closing_debit, "closing_credit": closing_credit,
        "opening_debit": closing_debit, "opening_credit": closing_credit,
        "source_anchor": ANCHOR, "requires_auxiliary": True, "auxiliary": auxiliary,
    }


def supplier(key, debit="0.00", credit="0.00"):
    return {"key": key, "closing_debit": debit, "closing_credit": credit,
            "opening_debit": debit, "opening_credit": credit, "source_anchor": ANCHOR}


def test_control_account_shown_net_accepts_details_with_both_directions():
    """贷方 249,386.78 − 借方 50,292.10 = 199,094.68，与控制科目净额一致。"""
    account = AccountBalance.model_validate(payable([
        supplier("昆山市荣信发金属有限公司", credit="249386.78"),
        supplier("江苏帝全自动化机械有限公司", debit="50292.10"),
    ]))
    assert account.closing_credit == Decimal("199094.68")
    # 明细各自的方向必须原样保留，它们是后续往来核销的依据。
    assert [a.closing_debit for a in account.auxiliary] == [Decimal("0.00"), Decimal("50292.10")]
    assert [a.closing_credit for a in account.auxiliary] == [Decimal("249386.78"), Decimal("0.00")]


def test_details_matching_only_by_gross_are_still_rejected():
    """净额相同才算一致；凑出来的总额相同但净额不同必须拦下。"""
    with pytest.raises(ValidationError, match="辅助明细与科目控制余额不一致"):
        AccountBalance.model_validate(payable([
            supplier("甲", credit="249386.78"),
            supplier("乙", debit="50292.11"),
        ]))


def test_single_direction_details_still_work():
    account = AccountBalance.model_validate(payable([
        supplier("甲", credit="100000.00"),
        supplier("乙", credit="99094.68"),
    ]))
    assert len(account.auxiliary) == 2


def test_each_detail_must_carry_the_same_opening_as_closing():
    """基线上本期期初就是上期期末，每一项都必须自洽 —— 这道先于净额比较生效。"""
    item = payable([supplier("甲", credit="249386.78"), supplier("乙", debit="50292.10")])
    item["auxiliary"][0]["opening_credit"] = "249386.79"
    with pytest.raises(ValidationError, match="本期期初与上期期末余额不一致"):
        AccountBalance.model_validate(item)



def test_an_account_needing_auxiliary_without_details_is_rejected():
    with pytest.raises(ValidationError, match="需要辅助核算的科目缺少明细"):
        AccountBalance.model_validate(payable([]))


def test_duplicate_auxiliary_keys_are_rejected():
    with pytest.raises(ValidationError, match="辅助核算明细重复"):
        AccountBalance.model_validate(payable([
            supplier("甲", credit="199094.68"), supplier("甲", credit="0.00")]))


def test_an_account_without_auxiliary_is_unaffected():
    account = AccountBalance.model_validate({
        "account_code": "1002", "account_name": "银行存款",
        "closing_debit": "101017.78", "closing_credit": "0.00",
        "opening_debit": "101017.78", "opening_credit": "0.00",
        "source_anchor": ANCHOR, "requires_auxiliary": False, "auxiliary": []})
    assert account.closing_debit == Decimal("101017.78")
