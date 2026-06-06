from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import Base, SessionLocal, engine
from app.models import Enterprise
from app.schemas.technology_profile import TechnologyScanResultInput
from app.services.technology_profile_service import upsert_scan_results


def import_profiles_from_file(db: Session, path: str | Path) -> dict[str, int | list[str]]:
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Technology profile import file must contain a JSON array.")
    updated = 0
    skipped = []
    for record in records:
        enterprise = _find_enterprise(db, record)
        if enterprise is None:
            skipped.append(str(record.get("enterprise_name") or record.get("unified_social_credit_code") or "UNKNOWN"))
            continue
        payload = _scan_payload(record)
        upsert_scan_results(db, enterprise.id, payload)
        updated += 1
    return {"updated": updated, "skipped": skipped}


def _scan_payload(record: dict[str, Any]) -> TechnologyScanResultInput:
    if record.get("qichacha_innovation_text"):
        from app.services.qichacha_innovation_parser import parse_qichacha_innovation_text

        parsed = parse_qichacha_innovation_text(record["qichacha_innovation_text"])
        parsed["raw_snapshot"] = {
            **parsed.get("raw_snapshot", {}),
            **record.get("raw_snapshot", {}),
        }
        for tag in parsed["tags"]:
            tag.setdefault("source_url", record.get("source_url"))
        return TechnologyScanResultInput(**parsed)
    return TechnologyScanResultInput(
        provider=record.get("provider", "MANUAL"),
        summary=record.get("summary", ""),
        raw_snapshot=record.get("raw_snapshot", {}),
        tags=record.get("tags", []),
    )


def _find_enterprise(db: Session, record: dict[str, Any]) -> Enterprise | None:
    credit_code = (record.get("unified_social_credit_code") or "").strip()
    if credit_code:
        enterprise = db.scalar(select(Enterprise).where(Enterprise.unified_social_credit_code == credit_code))
        if enterprise is not None:
            return enterprise
    name = (record.get("enterprise_name") or "").strip()
    if not name:
        return None
    return db.scalar(select(Enterprise).where(Enterprise.name == name))


def main() -> None:
    parser = argparse.ArgumentParser(description="Import FinWise technology qualification profile JSON.")
    parser.add_argument("path", help="Path to a JSON file with technology profile records.")
    args = parser.parse_args()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        result = import_profiles_from_file(db, args.path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
