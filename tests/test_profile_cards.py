"""识别确认卡：未知版式变成一张可一次确认的卡片，确认后沉淀成规则。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.profile_cards import adopt_profile_card, build_profile_card
from app.source_profiles import ProfileMapping, ProfileStore, fingerprint
from app.tabular import ParseOptions, extract_workbook, read_workbook
from app.task_descriptors import WhyDescriptor
from test_profile_driven_parsing import TERSE, TERSE_ROWS, workbook


@pytest.fixture()
def store(tmp_path: Path) -> ProfileStore:
    settings = Settings(root=Path(__file__).resolve().parents[1],
                        database_path=tmp_path / "c.db", storage_path=tmp_path / "a", require_auth=False)
    database = Database(settings)
    database.initialize()
    return ProfileStore(database)


def sheet_of(rows):
    return read_workbook(workbook(rows))[0]


# ---------- 契约 ----------

def test_why_descriptor_accepts_agent_origin_with_confidence_and_yields():
    why = WhyDescriptor(facts="f", rule="r", recommendation="a", origin="AGENT", confidence=88,
                        yields={"kind": "SOURCE_PROFILE", "key": "abc", "summary": "s"}, evidence=[])
    assert why.origin == "AGENT" and why.confidence == 88
    assert why.yields.kind == "SOURCE_PROFILE" and why.yields.scope_level == "ENTITY"


def test_why_descriptor_still_defaults_to_rule_origin():
    why = WhyDescriptor(facts="f", rule="r", recommendation="a", evidence=[])
    assert why.origin == "RULE" and why.confidence == 100 and why.yields is None


def test_why_descriptor_rejects_unknown_origin_and_out_of_range_confidence():
    with pytest.raises(ValueError):
        WhyDescriptor(facts="f", rule="r", recommendation="a", origin="ROBOT", evidence=[])
    with pytest.raises(ValueError):
        WhyDescriptor(facts="f", rule="r", recommendation="a", confidence=101, evidence=[])


# ---------- 出卡 ----------

def test_unknown_layout_produces_a_confirmation_card_with_evidence(store: ProfileStore):
    card = build_profile_card(sheet=sheet_of([TERSE] + TERSE_ROWS), document_kind="bank_statement",
                              filename="某行流水.xlsx", store=store)
    assert card["card_type"] == "SOURCE_PROFILE_CONFIRM"
    assert card["why"]["origin"] == "AGENT" and card["why"]["confidence"] > 0
    assert "支出＝借" in card["why"]["facts"] and "收入＝贷" in card["why"]["facts"]
    assert any("余额连续性" in part for part in card["why"]["rule"].split("；"))
    assert [option["id"] for option in card["options"]] == ["confirm_profile", "designate_profile_columns"]


def test_card_declares_what_confirming_it_will_persist(store: ProfileStore):
    card = build_profile_card(sheet=sheet_of([TERSE] + TERSE_ROWS), document_kind="bank_statement",
                              filename="某行流水.xlsx", store=store)
    draft = card["why"]["yields"]
    assert draft["kind"] == "SOURCE_PROFILE"
    assert draft["key"] == fingerprint(TERSE, "bank_statement")


def test_no_card_once_the_layout_is_already_known(store: ProfileStore):
    store.record(fingerprint_value=fingerprint(TERSE, "bank_statement"), document_kind="bank_statement",
                 label="已确认", origin="HUMAN",
                 mapping=ProfileMapping(header_row=1, fields={"transaction_date": [0], "expense": [1], "income": [2]}))
    assert build_profile_card(sheet=sheet_of([TERSE] + TERSE_ROWS), document_kind="bank_statement",
                              filename="某行流水.xlsx", store=store) is None


def test_unverifiable_layout_asks_for_human_designation_instead_of_guessing(store: ProfileStore):
    rows = [['交易时间', '金额甲', '金额乙', '余额'],
            ['2026-01-02', '10.00', '20.00', '999.00'],
            ['2026-01-03', '30.00', '40.00', '111.00']]
    card = build_profile_card(sheet=sheet_of(rows), document_kind="bank_statement",
                              filename="怪格式.xlsx", store=store)
    assert card["card_type"] == "SOURCE_PROFILE_UNKNOWN"
    assert card["why"]["confidence"] == 0
    assert "designate_profile_columns" in {option["id"] for option in card["options"]}
    assert "proposal" not in card


def test_thin_evidence_card_tells_the_operator_to_check_before_confirming(store: ProfileStore):
    """三行只有两次余额比对：可以提案，但置信度必须低到需要人工核对。"""
    card = build_profile_card(sheet=sheet_of([TERSE] + TERSE_ROWS), document_kind="bank_statement",
                              filename="三行.xlsx", store=store)
    assert card["card_type"] == "SOURCE_PROFILE_CONFIRM"
    assert card["why"]["confidence"] < 90
    assert "核对" in card["why"]["recommendation"]


def test_two_rows_are_too_thin_to_propose_at_all(store: ProfileStore):
    """只有一次余额比对时不出提案 —— 宁可说认不出，也不给一个凑出来的方向。"""
    card = build_profile_card(sheet=sheet_of([TERSE] + TERSE_ROWS[:2]), document_kind="bank_statement",
                              filename="两行.xlsx", store=store)
    assert card["card_type"] == "SOURCE_PROFILE_UNKNOWN"


# ---------- 确认即沉淀 ----------

def test_confirming_a_card_registers_the_profile_and_stops_further_cards(store: ProfileStore):
    content = workbook([TERSE] + TERSE_ROWS)
    card = build_profile_card(sheet=read_workbook(content)[0], document_kind="bank_statement",
                              filename="某行流水.xlsx", store=store)
    saved = adopt_profile_card(card=card, store=store, actor="alice", document_kind="bank_statement")
    assert saved.origin == "HUMAN" and saved.confirmed_by == "alice"
    assert build_profile_card(sheet=read_workbook(content)[0], document_kind="bank_statement",
                              filename="某行流水.xlsx", store=store) is None


def test_confirmed_profile_immediately_parses_the_same_layout(store: ProfileStore):
    content = workbook([TERSE] + TERSE_ROWS)
    options = ParseOptions(document_kind="bank_statement", bank_account_ref="ACCT-1")

    def resolver(labels, kind):
        found = store.resolve(fingerprint_value=fingerprint(labels, kind), document_kind=kind)
        return found.mapping if found else None

    assert extract_workbook(content, options, "2026-01", resolver=resolver)["records"] == []
    card = build_profile_card(sheet=read_workbook(content)[0], document_kind="bank_statement",
                              filename="某行流水.xlsx", store=store)
    adopt_profile_card(card=card, store=store, actor="alice", document_kind="bank_statement")
    after = extract_workbook(content, options, "2026-01", resolver=resolver)
    assert len(after["records"]) == 3 and all(not r["extraction_issues"] for r in after["records"])


def test_entity_scoped_confirmation_does_not_leak_to_another_tenant(store: ProfileStore):
    content = workbook([TERSE] + TERSE_ROWS)
    card = build_profile_card(sheet=read_workbook(content)[0], document_kind="bank_statement",
                              filename="某行流水.xlsx", store=store, tenant_id="t1", legal_entity_id="e1")
    assert card["why"]["yields"]["scope_level"] == "ENTITY"
    adopt_profile_card(card=card, store=store, actor="alice", document_kind="bank_statement",
                       tenant_id="t1", legal_entity_id="e1")
    assert build_profile_card(sheet=read_workbook(content)[0], document_kind="bank_statement",
                              filename="某行流水.xlsx", store=store,
                              tenant_id="t2", legal_entity_id="e9") is not None


def test_unknown_card_cannot_be_adopted_without_human_designation(store: ProfileStore):
    rows = [['交易时间', '金额甲', '金额乙', '余额'],
            ['2026-01-02', '10.00', '20.00', '999.00'],
            ['2026-01-03', '30.00', '40.00', '111.00']]
    card = build_profile_card(sheet=sheet_of(rows), document_kind="bank_statement",
                              filename="怪格式.xlsx", store=store)
    with pytest.raises(ValueError, match="只有带提案"):
        adopt_profile_card(card=card, store=store, actor="alice", document_kind="bank_statement")


def test_abstained_proposal_still_fingerprints_the_real_header(store: ProfileStore):
    """弃权时也必须用真正的表头算指纹。

    退回"第一个非空行"会把标题行算进去——那一行常含企业名称，
    既让指纹失去复用价值，也把业务值带进了本应可跨租户共享的键。
    """
    rows = [['企业名称', '某某有限公司'],
            ['账号', '123456'],
            ['交易时间', '金额甲', '金额乙', '余额'],
            ['2026-01-02', '10.00', '20.00', '999.00'],
            ['2026-01-03', '30.00', '40.00', '111.00']]
    card = build_profile_card(sheet=sheet_of(rows), document_kind="bank_statement",
                              filename="怪格式.xlsx", store=store)
    assert card["card_type"] == "SOURCE_PROFILE_UNKNOWN"
    assert card["why"]["yields"]["key"] == fingerprint(rows[2], "bank_statement")
    assert "某某有限公司" not in card["why"]["facts"]


def test_card_without_any_locatable_header_carries_no_fingerprint(store: ProfileStore):
    """连表头都定位不到时不编造指纹，等人工指认表头行之后再说。"""
    card = build_profile_card(sheet=sheet_of([['只有一行说明文字']]), document_kind="bank_statement",
                              filename="说明.xlsx", store=store)
    assert card["card_type"] == "SOURCE_PROFILE_UNKNOWN"
    assert card["why"]["yields"] is None and card["fingerprint"] == ""
