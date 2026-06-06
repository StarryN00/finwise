from __future__ import annotations

import re


QUALIFICATION_NAMES = [
    "科技型中小企业",
    "高新技术企业",
    "专精特新“小巨人”企业",
    "专精特新中小企业",
    "创新型中小企业",
    "制造业单项冠军示范企业",
    "制造业单项冠军产品企业",
    "独角兽企业",
    "瞪羚企业",
    "雏鹰企业",
]

IP_COUNT_NAMES = [
    "有效发明专利",
    "有效实用新型",
    "有效外观设计",
    "发明专利申请",
    "软件著作权",
]


def parse_qichacha_innovation_text(text: str) -> dict:
    normalized = _normalize_text(text)
    tags = []
    for name in QUALIFICATION_NAMES:
        status = _qualification_status(normalized, name)
        if status == "HIT":
            tags.append(
                {
                    "category": "QCC_TECH_CERTIFICATION",
                    "name": name,
                    "status": "HIT",
                    "value": "企查查科创分",
                    "confidence": 95,
                    "evidence_text": _evidence_slice(normalized, name),
                }
            )
    for name in IP_COUNT_NAMES:
        value = _next_number(normalized, name)
        if value is not None:
            tags.append(
                {
                    "category": "QCC_INTELLECTUAL_PROPERTY",
                    "name": name,
                    "status": "HIT",
                    "value": value,
                    "confidence": 95,
                    "evidence_text": f"{name} {value}",
                }
            )
    return {
        "provider": "QICHACHA",
        "summary": _summary(normalized),
        "raw_snapshot": {
            "source": "qichacha_innovation_score_text",
            "score": _next_number(normalized, "科创分"),
            "level": _innovation_level(normalized),
            "industry": _match_group(normalized, r"所属国标二级行业[:：]\s*([^\n]+)"),
            "rank": _match_group(normalized, r"同行业内科创分排名\s*(前\d+%)"),
        },
        "tags": tags,
    }


def _qualification_status(text: str, name: str) -> str | None:
    line = next((line for line in text.splitlines() if name in line), "")
    if not line:
        return None
    window = line
    if any(marker in window for marker in ("✓", "√", "✔", "匹配", "是")) and "×" not in window:
        return "HIT"
    if any(marker in window for marker in ("×", "✕", "✖", "未匹配", "否")):
        return "NOT_HIT"
    return "PENDING_REVIEW"


def _next_number(text: str, label: str) -> str | None:
    pattern = rf"{re.escape(label)}\s*(?:\n|\s|:|：)*(\d+)"
    match = re.search(pattern, text)
    if match:
        return match.group(1)
    return None


def _summary(text: str) -> str:
    score = _next_number(text, "科创分")
    level = _innovation_level(text)
    industry = _match_group(text, r"所属国标二级行业[:：]\s*([^\n]+)")
    rank = _match_group(text, r"同行业内科创分排名\s*(前\d+%)")
    parts = []
    if score:
        parts.append(f"科创分{score}")
    if level:
        parts.append(f"等级{level}")
    if industry:
        parts.append(f"行业{industry}")
    if rank:
        parts.append(f"同行排名{rank}")
    return "，".join(parts) + "。" if parts else "已解析企查查科创分结构化文本。"


def _innovation_level(text: str) -> str:
    for level in ("优秀", "良好", "一般", "较弱"):
        if level in text:
            return level
    return ""


def _match_group(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _evidence_slice(text: str, label: str) -> str:
    idx = text.find(label)
    if idx < 0:
        return label
    return text[idx : idx + 80].replace("\n", " ").strip()


def _normalize_text(text: str) -> str:
    return "\n".join(line.strip() for line in (text or "").splitlines() if line.strip())
