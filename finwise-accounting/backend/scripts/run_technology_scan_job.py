from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from uuid import UUID

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.technology_scan_job_service import get_scan_job, serialize_job


def classify_interruption_reason(message: str) -> str:
    normalized = (message or "").lower()
    if any(keyword in normalized for keyword in ("captcha", "验证码", "验证")):
        return "CAPTCHA_REQUIRED"
    if any(keyword in normalized for keyword in ("login", "sign in", "登录")):
        return "LOGIN_REQUIRED"
    if any(keyword in normalized for keyword in ("ambiguous", "重名", "主体不确定")):
        return "AMBIGUOUS_MATCH"
    if any(keyword in normalized for keyword in ("科创分", "innovation panel")):
        return "NO_INNOVATION_PANEL"
    if any(keyword in normalized for keyword in ("rate limit", "访问受限", "限流", "请求过快")):
        return "PROVIDER_RATE_LIMITED"
    if any(keyword in normalized for keyword in ("not found", "未找到")):
        return "NOT_FOUND"
    return "UNKNOWN_ERROR"


def safe_log_message(message: str) -> str:
    text = message or ""
    text = re.sub(r"(?i)(password|cookie|token)=\S+", r"\1=***", text)
    text = re.sub(r"<[^>]+>", "[html-redacted]", text)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a FinWise technology scan job skeleton.")
    parser.add_argument("job_id", help="Technology scan job UUID.")
    args = parser.parse_args()
    with SessionLocal() as db:
        job, items = get_scan_job(db, UUID(args.job_id))
        pending = [item for item in items if item.status == "PENDING"]
        payload = {
            "job_id": str(job.id),
            "provider": job.provider,
            "status": job.status,
            "pending_item_count": len(pending),
            "message": "采集器骨架已读取任务；真实浏览器采集将在后续适配器中接入。",
        }
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
