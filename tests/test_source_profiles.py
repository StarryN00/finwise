from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.source_profiles import (
    ProfileMapping, ProfileStore, fingerprint, normalize_label,
)


@pytest.fixture()
def store(tmp_path: Path) -> ProfileStore:
    settings = Settings(root=Path(__file__).resolve().parents[1],
                        database_path=tmp_path / "p.db", storage_path=tmp_path / "a", require_auth=False)
    database = Database(settings)
    database.initialize()
    return ProfileStore(database)


def two_column(**overrides) -> ProfileMapping:
    base = dict(header_row=1, fields={"transaction_date": [0], "expense": [1], "income": [2]})
    base.update(overrides)
    return ProfileMapping(**base)


# ---------- 指纹 ----------

def test_fingerprint_ignores_column_order_whitespace_and_fullwidth():
    a = fingerprint(["交易日期", "借方金额", "贷方金额"], "bank_statement")
    b = fingerprint(["贷方金额", " 交易日期 ", "借方\n金额"], "bank_statement")
    c = fingerprint(["交易日期", "借方金额", "贷方金额"], "bank_statement")
    assert a == b == c


def test_fingerprint_ignores_trailing_blank_columns():
    assert fingerprint(["交易日期", "收入", "支出"], "bank_statement") == \
           fingerprint(["交易日期", "收入", "支出", None, "", "  "], "bank_statement")


def test_fingerprint_separates_document_kinds_and_distinct_headers():
    assert fingerprint(["金额"], "bank_statement") != fingerprint(["金额"], "purchase_invoices")
    assert fingerprint(["借", "贷"], "bank_statement") != fingerprint(["借方", "贷方"], "bank_statement")


def test_normalize_label_folds_fullwidth_digits_and_case():
    assert normalize_label("ＡＢＣ１２") == "abc12"


def test_fingerprint_is_header_only_and_never_sees_data():
    """同一模板、不同月份的数据，指纹必须相同 —— 这是复用的前提。"""
    january = fingerprint(["交易日期", "收入", "支出", "余额"], "bank_statement")
    february = fingerprint(["交易日期", "收入", "支出", "余额"], "bank_statement")
    assert january == february


# ---------- 映射校验 ----------

def test_two_column_requires_both_sides():
    with pytest.raises(ValueError, match="借贷分列"):
        ProfileMapping(header_row=1, fields={"transaction_date": [0], "expense": [1]})


def test_direction_single_requires_direction_vocabulary():
    with pytest.raises(ValueError, match="方向列版式必须声明"):
        ProfileMapping(header_row=1, amount_model="DIRECTION_SINGLE",
                       fields={"transaction_date": [0], "amount": [1], "direction": [2]})


def test_signed_single_needs_amount_only():
    mapping = ProfileMapping(header_row=1, amount_model="SIGNED_SINGLE",
                             fields={"transaction_date": [0], "amount": [1]})
    assert mapping.covers("bank_statement")


def test_mapping_rejects_empty_or_out_of_range_columns():
    with pytest.raises(ValueError, match="列下标不能为空"):
        two_column(fields={"transaction_date": [], "expense": [1], "income": [2]})
    with pytest.raises(ValueError, match="列下标越界"):
        two_column(fields={"transaction_date": [0], "expense": [1], "income": [999]})


def test_mapping_never_carries_business_values():
    """版式只能是指针。任何未声明的字段都必须被拒绝。"""
    with pytest.raises(ValueError):
        ProfileMapping(header_row=1, fields={"transaction_date": [0], "expense": [1], "income": [2]},
                       balance_amount="12345.67")


def test_null_tokens_recognize_dash_as_structural_blank():
    mapping = two_column()
    assert mapping.is_null("-") and mapping.is_null("") and mapping.is_null(None)
    assert not mapping.is_null("0.00") and not mapping.is_null("8732.00")


# ---------- 存取 ----------

def test_record_and_resolve_platform_profile(store: ProfileStore):
    key = fingerprint(["交易日期", "借", "贷"], "bank_statement")
    saved = store.record(fingerprint_value=key, document_kind="bank_statement",
                         label="微众银行 交易明细", mapping=two_column(), origin="AGENT", confidence=80)
    found = store.resolve(fingerprint_value=key, document_kind="bank_statement")
    assert found is not None and found.profile_id == saved.profile_id
    assert found.label == "微众银行 交易明细" and found.origin == "AGENT"


def test_resolve_miss_returns_none_not_error(store: ProfileStore):
    assert store.resolve(fingerprint_value="x" * 64, document_kind="bank_statement") is None


def test_resolve_counts_hits_for_promotion(store: ProfileStore):
    key = fingerprint(["交易日期", "借", "贷"], "bank_statement")
    saved = store.record(fingerprint_value=key, document_kind="bank_statement",
                         label="L", mapping=two_column(), origin="SEED")
    for _ in range(3):
        store.resolve(fingerprint_value=key, document_kind="bank_statement")
    assert store.get(saved.profile_id).hit_count == 3
    store.resolve(fingerprint_value=key, document_kind="bank_statement", count_hit=False)
    assert store.get(saved.profile_id).hit_count == 3


def test_entity_profile_beats_tenant_beats_platform(store: ProfileStore):
    key = fingerprint(["交易日期", "借", "贷"], "bank_statement")
    common = dict(fingerprint_value=key, document_kind="bank_statement", mapping=two_column(), origin="HUMAN")
    store.record(label="平台版", scope_level="PLATFORM", **common)
    store.record(label="租户版", scope_level="TENANT", tenant_id="t1", **common)
    store.record(label="企业版", scope_level="ENTITY", tenant_id="t1", legal_entity_id="e1", **common)

    assert store.resolve(fingerprint_value=key, document_kind="bank_statement",
                         tenant_id="t1", legal_entity_id="e1").label == "企业版"
    assert store.resolve(fingerprint_value=key, document_kind="bank_statement",
                         tenant_id="t1", legal_entity_id="other").label == "租户版"
    assert store.resolve(fingerprint_value=key, document_kind="bank_statement",
                         tenant_id="t2", legal_entity_id="e9").label == "平台版"


def test_tenant_profile_is_invisible_to_other_tenants(store: ProfileStore):
    key = fingerprint(["交易日期", "借", "贷"], "bank_statement")
    store.record(fingerprint_value=key, document_kind="bank_statement", label="仅租户1",
                 mapping=two_column(), origin="HUMAN", scope_level="TENANT", tenant_id="t1")
    assert store.resolve(fingerprint_value=key, document_kind="bank_statement", tenant_id="t2") is None


def test_recording_same_fingerprint_retires_previous_version(store: ProfileStore):
    key = fingerprint(["交易日期", "借", "贷"], "bank_statement")
    first = store.record(fingerprint_value=key, document_kind="bank_statement", label="v1",
                         mapping=two_column(), origin="AGENT")
    second = store.record(fingerprint_value=key, document_kind="bank_statement", label="v2",
                          mapping=two_column(header_row=2), origin="HUMAN")
    assert store.resolve(fingerprint_value=key, document_kind="bank_statement").profile_id == second.profile_id
    assert [p.profile_id for p in store.list_profiles()] == [second.profile_id]
    assert first.profile_id in {p.profile_id for p in store.list_profiles(include_retired=True)}


def test_confirm_turns_agent_proposal_into_human_rule(store: ProfileStore):
    key = fingerprint(["交易日期", "借", "贷"], "bank_statement")
    saved = store.record(fingerprint_value=key, document_kind="bank_statement", label="L",
                         mapping=two_column(), origin="AGENT", confidence=70)
    confirmed = store.confirm(saved.profile_id, actor="alice")
    assert confirmed.origin == "HUMAN" and confirmed.confidence == 100
    assert confirmed.confirmed_by == "alice" and confirmed.confirmed_at


def test_record_rejects_mapping_that_misses_required_fields(store: ProfileStore):
    mapping = ProfileMapping(header_row=1, amount_model="SIGNED_SINGLE", fields={"amount": [1]})
    with pytest.raises(ValueError, match="必要字段"):
        store.record(fingerprint_value="f" * 64, document_kind="bank_statement",
                     label="缺日期", mapping=mapping, origin="AGENT")


def test_scope_level_arguments_are_enforced(store: ProfileStore):
    common = dict(fingerprint_value="a" * 64, document_kind="bank_statement",
                  label="L", mapping=two_column(), origin="SEED")
    with pytest.raises(ValueError, match="TENANT 级"):
        store.record(scope_level="TENANT", **common)
    with pytest.raises(ValueError, match="ENTITY 级"):
        store.record(scope_level="ENTITY", tenant_id="t1", **common)


# ---------- 晋升 ----------

def test_entity_profile_becomes_promotable_after_confirmed_hits(store: ProfileStore):
    key = fingerprint(["交易日期", "借", "贷"], "bank_statement")
    saved = store.record(fingerprint_value=key, document_kind="bank_statement", label="企业版",
                         mapping=two_column(), origin="AGENT", scope_level="ENTITY",
                         tenant_id="t1", legal_entity_id="e1")
    assert store.promotable() == []
    store.confirm(saved.profile_id, actor="alice")
    for _ in range(3):
        store.resolve(fingerprint_value=key, document_kind="bank_statement",
                      tenant_id="t1", legal_entity_id="e1")
    assert [p.profile_id for p in store.promotable()] == [saved.profile_id]


def test_tenant_profile_promotes_to_platform_only_after_two_tenants(store: ProfileStore):
    key = fingerprint(["交易日期", "借", "贷"], "bank_statement")
    ids = []
    for tenant in ("t1", "t2"):
        saved = store.record(fingerprint_value=key, document_kind="bank_statement", label=f"{tenant}版",
                             mapping=two_column(), origin="AGENT", scope_level="TENANT", tenant_id=tenant)
        store.confirm(saved.profile_id, actor="alice")
        ids.append(saved.profile_id)
    for _ in range(3):
        store.resolve(fingerprint_value=key, document_kind="bank_statement", tenant_id="t1")
    assert [p.profile_id for p in store.promotable()] == [ids[0]]


def test_promote_lifts_scope_and_keeps_mapping(store: ProfileStore):
    key = fingerprint(["交易日期", "借", "贷"], "bank_statement")
    saved = store.record(fingerprint_value=key, document_kind="bank_statement", label="企业版",
                         mapping=two_column(header_row=4), origin="HUMAN", scope_level="ENTITY",
                         tenant_id="t1", legal_entity_id="e1")
    lifted = store.promote(saved.profile_id, actor="alice")
    assert lifted.scope_level == "TENANT" and lifted.tenant_id == "t1"
    assert lifted.mapping.header_row == 4
    assert store.promote(lifted.profile_id, actor="alice").scope_level == "PLATFORM"


def test_platform_profile_cannot_be_promoted_further(store: ProfileStore):
    saved = store.record(fingerprint_value="b" * 64, document_kind="bank_statement",
                         label="L", mapping=two_column(), origin="SEED")
    with pytest.raises(ValueError, match="最高作用域"):
        store.promote(saved.profile_id, actor="alice")


def test_retired_profile_stops_resolving(store: ProfileStore):
    key = fingerprint(["交易日期", "借", "贷"], "bank_statement")
    saved = store.record(fingerprint_value=key, document_kind="bank_statement", label="L",
                         mapping=two_column(), origin="SEED")
    store.retire(saved.profile_id)
    assert store.resolve(fingerprint_value=key, document_kind="bank_statement") is None
