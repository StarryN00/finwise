"""按摘要判断科目：模型只能在企业自己在用的科目里选。"""
from __future__ import annotations

import pytest

from app.account_classifier import (
    AccountChoice, auto_adoptable, candidates, classify, party_history,
)
from app.voucher_history import AccountRule, Voucher, VoucherLine

VOCABULARY = [
    AccountRule(pattern="办公费", account_code="560202", account_name="办公费", seen=48, examples=["记-001"]),
    AccountRule(pattern="原材料", account_code="1403", account_name="原材料", seen=32),
    AccountRule(pattern="福利费", account_code="560211", account_name="福利费", seen=18),
    AccountRule(pattern="差旅费", account_code="560205", account_name="差旅费", seen=14),
    AccountRule(pattern="销售费用_差旅费", account_code="560106", account_name="销售费用_差旅费", seen=4),
]


class FakeReader:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.seen: list[dict] = []

    def classify(self, payload):
        self.seen.append(payload)
        value = self.payloads[min(len(self.seen) - 1, len(self.payloads) - 1)]
        if isinstance(value, Exception):
            raise value
        return value


def choose(reply, **kw):
    return classify(summary=kw.pop("summary", "购买水果礼盒"),
                    counterparty=kw.pop("counterparty", "侯文军"),
                    amount="3278.00", direction="PAYMENT",
                    vocabulary=kw.pop("vocabulary", VOCABULARY),
                    reader=FakeReader(reply), **kw)


def test_a_pick_from_the_company_vocabulary_is_accepted():
    choice = choose({"outcome": "PICK", "account_code": "560211", "account_name": "随便写的名字",
                     "reason": "属职工福利", "evidence": ["记-018"], "confidence": 90})
    assert choice.outcome == "PICK" and choice.account_code == "560211"
    # 名称以账套为准，不采信模型自己写的。
    assert choice.account_name == "福利费"


def test_an_invented_account_is_refused_even_if_it_looks_plausible():
    """闭集必须在代码里再核一次。写在提示词里的"不许发明科目"不是保证。"""
    choice = choose({"outcome": "PICK", "account_code": "660301", "account_name": "招待费",
                     "reason": "看起来合理", "evidence": [], "confidence": 99})
    assert choice.outcome == "ABSTAIN"
    assert "不在该企业在用科目内" in choice.reason


def test_an_abstain_is_passed_through():
    choice = choose({"outcome": "ABSTAIN", "reason": "候选里没有房租科目", "confidence": 0})
    assert choice.outcome == "ABSTAIN" and "房租" in choice.reason


def test_a_reply_with_unknown_fields_becomes_an_abstain_not_a_crash():
    choice = choose({"outcome": "PICK", "account_code": "560211", "guess": True})
    assert choice.outcome == "ABSTAIN" and "科目判断未完成" in choice.reason


def test_a_pick_without_an_account_code_is_named_precisely():
    """含糊的报错会把人引向错误的方向，说清楚是"声称选了却没给编码"。"""
    choice = choose({"outcome": "PICK"})
    assert choice.outcome == "ABSTAIN"
    assert "没有给出科目编码" in choice.reason


def test_a_provider_failure_becomes_an_abstain():
    choice = classify(summary="餐费", counterparty="侯文军", amount="1.00", direction="PAYMENT",
                      vocabulary=VOCABULARY, reader=FakeReader(RuntimeError("服务不可达")))
    assert choice.outcome == "ABSTAIN" and "科目判断未完成" in choice.reason


def test_an_empty_vocabulary_abstains_without_calling_the_model():
    reader = FakeReader({"outcome": "PICK", "account_code": "560202", "confidence": 99})
    choice = classify(summary="餐费", counterparty="甲", amount="1.00", direction="PAYMENT",
                      vocabulary=[], reader=reader)
    assert choice.outcome == "ABSTAIN" and reader.seen == []


def test_the_model_only_ever_sees_accounts_the_company_already_uses():
    reader = FakeReader({"outcome": "ABSTAIN", "reason": "x"})
    classify(summary="餐费", counterparty="甲", amount="1.00", direction="PAYMENT",
             vocabulary=VOCABULARY, reader=reader)
    offered = {item["account_code"] for item in reader.seen[0]["candidates"]}
    assert offered == {rule.account_code for rule in VOCABULARY}


def test_candidates_are_ordered_by_how_much_the_company_uses_them():
    assert [item["account_code"] for item in candidates(VOCABULARY)][:2] == ["560202", "1403"]


# ---------- 往来对象的历史科目 ----------

def voucher(number, party, expense_code, expense_name):
    return Voucher(number=number, period="2026-07", date="2026-07-31", summary="差旅费", lines=[
        VoucherLine(account_code=expense_code, account_name=expense_name, debit="100.00"),
        VoucherLine(account_code="224105", account_name=party, credit="100.00"),
    ])


def test_party_history_reports_what_this_person_actually_used():
    """企业有两个差旅费科目，选哪个取决于这个人属哪个部门 —— 写在他过去的凭证里。"""
    history = party_history("陈阳", [
        voucher("记-006", "陈阳", "560106", "销售费用_差旅费"),
        voucher("记-013", "陈阳", "560106", "销售费用_差旅费"),
        voucher("记-018", "陈阳", "560205", "差旅费"),
        voucher("记-020", "侯文军", "560202", "办公费"),
    ])
    assert history[0]["account_code"] == "560106" and history[0]["used"] == 2
    assert {item["account_code"] for item in history} == {"560106", "560205"}


def test_party_history_is_empty_for_someone_new():
    assert party_history("黄鹏飞", [voucher("记-006", "陈阳", "560106", "差旅费")]) == []


def test_party_history_needs_a_name():
    assert party_history("", [voucher("记-006", "陈阳", "560106", "差旅费")]) == []


def test_party_history_reaches_the_model():
    reader = FakeReader({"outcome": "ABSTAIN", "reason": "x"})
    classify(summary="出差费用", counterparty="陈阳", amount="1.00", direction="PAYMENT",
             vocabulary=VOCABULARY, reader=reader,
             party_accounts=[{"account_code": "560106", "account_name": "销售费用_差旅费", "used": 3}])
    assert reader.seen[0]["party_history"][0]["account_code"] == "560106"


# ---------- 自动采用的闸门 ----------

def test_only_high_confidence_picks_may_be_adopted_without_review():
    assert auto_adoptable(AccountChoice(outcome="PICK", account_code="560202", confidence=90))
    assert not auto_adoptable(AccountChoice(outcome="PICK", account_code="560202", confidence=84))
    assert not auto_adoptable(AccountChoice(outcome="ABSTAIN", confidence=99))
