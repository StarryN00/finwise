from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, SessionLocal, engine
from app.models import Enterprise
from scripts.import_technology_profiles import import_profiles_from_file


ENV_PATHS = [
    Path("../.env"),
    Path(".env"),
    Path("../../.env.local"),
    Path(".env.local"),
]


def load_local_env() -> None:
    for path in ENV_PATHS:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def build_review_seed(records: list[Enterprise]) -> list[dict]:
    seed = []
    for enterprise in records:
        if enterprise.name == "昆山黛珂特电子科技有限公司":
            seed.append(
                {
                    "enterprise_name": enterprise.name,
                    "unified_social_credit_code": enterprise.unified_social_credit_code,
                    "provider": "QICHACHA",
                    "summary": "已创建企查查复查任务；需从科创分弹窗结构化文本确认科技资质和知识产权数量。",
                    "raw_snapshot": {"collection_mode": "public_evidence_seed", "needs_provider_review": True},
                    "tags": [],
                }
            )
        elif enterprise.name != "t":
            seed.append(
                {
                    "enterprise_name": enterprise.name,
                    "unified_social_credit_code": enterprise.unified_social_credit_code,
                    "provider": "QICHACHA",
                    "summary": "未自动取得可确认科技资质，已标记为需使用企查查或天眼查登录态复查。",
                    "raw_snapshot": {"collection_mode": "review_required", "needs_provider_review": True},
                    "tags": [],
                }
            )
    return seed


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare or import Qichacha technology profile scan results.")
    parser.add_argument("--seed-review", action="store_true", help="Create review-required profile records for current enterprises.")
    parser.add_argument("--output", default="storage/technology_profile_seed.json", help="Where to write the generated seed JSON.")
    args = parser.parse_args()
    load_local_env()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        enterprises = list(db.query(Enterprise).order_by(Enterprise.created_at))
        seed = build_review_seed(enterprises)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
        result = import_profiles_from_file(db, output_path) if args.seed_review else {"updated": 0, "skipped": []}
    print(json.dumps({"records": len(seed), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
