"""版式确认卡：把"这份文件我没见过"变成一张可以一次确认的卡片。

卡片只描述，不执行。确认动作由命令层完成，确认之后 yields 指明该登记哪条规则。
同一张表头的卡片在整个平台只需要确认一次，之后所有同模板的文件都直接命中版式。
"""
from __future__ import annotations

from typing import Any, Optional

from app.profile_proposals import MappingProposal, propose_mapping
from app.source_profiles import ProfileStore, SourceProfile, fingerprint

CARD_VERSION = "profile-card-v1"
# 低于这个置信度的提案不能自动采用，必须人工确认。
AUTO_ADOPT_CONFIDENCE = 90


def _field_summary(proposal: MappingProposal, labels: list[str]) -> str:
    def name(index: int) -> str:
        return labels[index] if 0 <= index < len(labels) and labels[index] else f"第{index + 1}列"

    parts = []
    for field, caption in (("transaction_date", "交易日期"), ("expense", "支出"), ("income", "收入"),
                           ("amount", "金额"), ("direction", "方向"), ("balance", "余额"),
                           ("counterparty", "对方"), ("summary", "摘要")):
        columns = proposal.mapping.fields.get(field) if proposal.mapping else None
        if columns:
            parts.append(f"{caption}＝{name(columns[0])}")
    return "；".join(parts)


def build_profile_card(
    *,
    sheet: dict[str, Any],
    document_kind: str,
    filename: str,
    store: ProfileStore,
    tenant_id: Optional[str] = None,
    legal_entity_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """未命中版式时产出一张待确认卡片；已命中则返回 None（不打扰人）。"""
    rows = sheet.get("rows") or []
    proposal = propose_mapping(sheet, document_kind)

    header_values = None
    if proposal.header_row:
        header_values = next((r["values"] for r in rows if r["row"] == proposal.header_row), None)
    if header_values is None:
        header_values = next((r["values"] for r in rows if any(str(v or "").strip() for v in r["values"])), [])

    key = fingerprint(header_values, document_kind)
    if store.resolve(fingerprint_value=key, document_kind=document_kind,
                     tenant_id=tenant_id, legal_entity_id=legal_entity_id, count_hit=False):
        return None

    labels = [str(v or "").strip() for v in header_values]
    scope_level = "ENTITY" if (tenant_id and legal_entity_id) else "PLATFORM"
    draft = {"kind": "SOURCE_PROFILE", "key": key,
             "summary": f"{filename}｜{sheet.get('name', '')}", "scope_level": scope_level}

    if proposal.outcome != "PROPOSAL" or proposal.mapping is None:
        # 提不出可验证的方案时，诚实地说"认不出"，让人工指认列，而不是给一个猜测。
        return {
            "version": CARD_VERSION,
            "card_type": "SOURCE_PROFILE_UNKNOWN",
            "title": f"认不出这份文件的结构：{filename}",
            "why": {
                "facts": f"表头：{'／'.join(x for x in labels if x)[:160] or '未能定位表头'}",
                "rule": "版式库没有这张表头，提案也无法用余额连续性验证收付方向",
                "recommendation": proposal.reason or "请人工指认日期、收入、支出与余额各在哪一列",
                "origin": "AGENT", "confidence": 0,
                "yields": draft, "evidence": [],
            },
            "options": [
                {"id": "designate_profile_columns", "label": "我来指认各列", "submit_label": "保存版式"},
                {"id": "skip_source", "label": "这份先跳过", "submit_label": "跳过"},
            ],
            "fingerprint": key,
        }

    return {
        "version": CARD_VERSION,
        "card_type": "SOURCE_PROFILE_CONFIRM",
        "title": f"确认这份文件的结构：{filename}",
        "why": {
            "facts": _field_summary(proposal, labels),
            "rule": "；".join(proposal.evidence),
            "recommendation": ("识别可信，确认后同模板文件不再询问"
                               if proposal.confidence >= AUTO_ADOPT_CONFIDENCE
                               else "证据偏少，请核对列的对应关系后再确认"),
            "origin": "AGENT", "confidence": proposal.confidence,
            "yields": draft, "evidence": [],
        },
        "options": [
            {"id": "confirm_profile", "label": "确认", "submit_label": "确认并登记版式"},
            {"id": "designate_profile_columns", "label": "我改一下", "submit_label": "保存版式"},
        ],
        "proposal": proposal.model_dump(mode="json"),
        "fingerprint": key,
    }


def adopt_profile_card(
    *,
    card: dict[str, Any],
    store: ProfileStore,
    actor: str,
    document_kind: str,
    tenant_id: Optional[str] = None,
    legal_entity_id: Optional[str] = None,
) -> SourceProfile:
    """人工确认一张识别卡：登记版式并记为 HUMAN 来源。"""
    if card.get("card_type") != "SOURCE_PROFILE_CONFIRM":
        raise ValueError("只有带提案的识别卡可以直接确认")
    from app.source_profiles import ProfileMapping

    proposal = card["proposal"]
    draft = card["why"]["yields"]
    saved = store.record(
        fingerprint_value=draft["key"], document_kind=document_kind,
        label=proposal.get("label_hint") or draft["summary"],
        mapping=ProfileMapping.model_validate(proposal["mapping"]),
        origin="AGENT", confidence=int(card["why"]["confidence"]),
        scope_level=draft["scope_level"],
        tenant_id=tenant_id if draft["scope_level"] != "PLATFORM" else None,
        legal_entity_id=legal_entity_id if draft["scope_level"] == "ENTITY" else None,
    )
    return store.confirm(saved.profile_id, actor=actor)
