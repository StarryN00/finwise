"""按学到的习惯为一笔流水提凭证。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.voucher_history import VoucherTemplate
from app.voucher_proposals import propose


def template(**kw):
    base = dict(party="侯文军", direction="PAYMENT", party_account="224101",
                party_account_name="侯文军", expense_accounts=[("560202", "办公费")],
                splits_input_tax=False, via_party=True, seen=33, settlements=30,
                examples=["记-001", "记-014"])
    base.update(kw)
    return VoucherTemplate(**base)


def make(templates=None, **kw):
    options = dict(bank_account_code="100201", bank_account_name="江苏银行0758",
                   counterparty="侯文军", summary="购买矿泉水", amount=Decimal("91.53"),
                   direction="PAYMENT",
                   templates=templates if templates is not None
                   else {("侯文军", "PAYMENT"): template()})
    options.update(kw)
    return propose(**options)


def sides(proposal):
    return [(l.account_code, str(l.debit) if l.debit else f"-{l.credit}") for l in proposal.lines]


# ---------- 基本结构 ----------

def test_a_reimbursement_goes_through_the_personal_payable_account():
    """代账公司的实际习惯：计提与付款合在一张凭证，经其他应付款过渡。"""
    proposal = make()
    assert proposal.outcome == "PROPOSAL" and proposal.balanced()
    assert sides(proposal) == [("560202", "91.53"), ("224101", "-91.53"),
                               ("224101", "91.53"), ("100201", "-91.53")]


def test_input_tax_is_split_out_when_an_invoice_backs_the_payment():
    proposal = make(templates={("侯文军", "PAYMENT"): template(splits_input_tax=True)},
                    input_tax=Decimal("7.76"), amount=Decimal("1507.30"))
    assert sides(proposal)[:2] == [("560202", "1499.54"), ("22210101", "7.76")]
    assert proposal.balanced()


def test_a_receipt_only_debits_the_bank():
    proposal = make(direction="RECEIPT", amount=Decimal("100000.00"),
                    counterparty="陈彩萍", summary="投资款",
                    templates={("陈彩萍", "RECEIPT"): template(
                        party="陈彩萍", direction="RECEIPT", party_account="300101",
                        party_account_name="陈彩萍", expense_accounts=[])})
    assert sides(proposal) == [("100201", "100000.00"), ("300101", "-100000.00")]


# ---------- 付款与收票是两件事 ----------

def test_a_payment_without_an_invoice_settles_the_payable_instead_of_abstaining():
    """真实账里记-007、记-010、记-012 都是纯付款冲应付，不确认费用也不拆税。
    历史上跟这个供应商收过票，不代表这一笔付款也带票。"""
    proposal = make(templates={("某供应商", "PAYMENT"): template(
                        party="某供应商", party_account="220217",
                        party_account_name="某供应商", splits_input_tax=True,
                        expense_accounts=[("1403", "原材料")])},
                    counterparty="某供应商", summary="货款", amount=Decimal("492.10"))
    assert proposal.outcome == "PROPOSAL"
    assert sides(proposal) == [("220217", "492.10"), ("100201", "-492.10")]
    assert any("按纯结算处理" in line for line in proposal.basis)


def test_settlement_only_confidence_asks_for_review():
    """"这笔付款确实没有票"是个假设，需要人确认。"""
    proposal = make(templates={("某供应商", "PAYMENT"): template(
                        party="某供应商", party_account="220217",
                        party_account_name="某供应商", splits_input_tax=True,
                        expense_accounts=[("1403", "原材料")])},
                    counterparty="某供应商", summary="货款", amount=Decimal("492.10"))
    assert proposal.confidence < 85


# ---------- 费用科目的来源 ----------

def test_an_explicit_expense_account_beats_the_party_default():
    """挂谁的账由往来对象决定，记什么费用由摘要决定 —— 两件事不能混。
    同一个人可以报销办公费、差旅费、餐费、福利费。"""
    proposal = make(summary="购买水果礼盒", amount=Decimal("3278.00"),
                    expense_account=("560211", "福利费"), expense_basis="属职工福利")
    assert sides(proposal)[0] == ("560211", "3278.00")
    assert "属职工福利" in proposal.basis


def test_without_an_explicit_account_the_party_default_is_used():
    assert sides(make())[0][0] == "560202"


# ---------- 弃权 ----------

def test_an_unknown_party_abstains():
    proposal = make(counterparty="黄鹏飞", templates={})
    assert proposal.outcome == "ABSTAIN" and "黄鹏飞" in proposal.reason


def test_a_transaction_without_a_counterparty_says_so():
    proposal = make(counterparty="", templates={})
    assert proposal.outcome == "ABSTAIN" and "没有对方户名" in proposal.reason


def test_a_party_with_no_expense_habit_abstains():
    proposal = make(templates={("侯文军", "PAYMENT"): template(expense_accounts=[])})
    assert proposal.outcome == "ABSTAIN" and "没有固定的费用或资产科目" in proposal.reason


# ---------- 置信度反映证据量 ----------

def test_confidence_grows_with_how_often_the_party_was_settled():
    few = make(templates={("侯文军", "PAYMENT"): template(seen=2, settlements=1)})
    many = make(templates={("侯文库", "PAYMENT"): template(seen=33, settlements=30)},
                counterparty="侯文库")
    assert few.confidence < many.confidence


def test_a_party_never_settled_is_less_certain():
    """只挂过账没付过款的对象，科目习惯可信但结算结构是推断的。"""
    unsettled = make(templates={("侯文军", "PAYMENT"): template(seen=5, settlements=0)})
    assert unsettled.confidence < 85


def test_multiple_historical_expense_accounts_lower_confidence():
    """历史上用过多个费用科目时，选哪个本身就不确定。"""
    single = make(templates={("侯文军", "PAYMENT"): template(
        expense_accounts=[("560202", "办公费")])})
    multiple = make(templates={("侯文军", "PAYMENT"): template(
        expense_accounts=[("560202", "办公费"), ("560205", "差旅费")])})
    assert multiple.confidence < single.confidence


def test_the_basis_names_the_vouchers_it_learned_from():
    proposal = make()
    assert any("记-001" in line for line in proposal.basis)
    assert any("过渡" in line for line in proposal.basis)


def test_every_proposal_balances():
    for proposal in (make(), make(input_tax=Decimal("1.00"), amount=Decimal("10.00")),
                     make(direction="RECEIPT", counterparty="陈彩萍",
                          templates={("陈彩萍", "RECEIPT"): template(
                              party="陈彩萍", direction="RECEIPT", party_account="300101",
                              party_account_name="陈彩萍", expense_accounts=[])})):
        if proposal.outcome == "PROPOSAL":
            assert proposal.balanced()
