from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import create_db_engine, create_session_factory  # noqa: E402
from app.models import MonthlyWorkPackage, Voucher, VoucherEntry  # noqa: E402


def main() -> None:
    args = _parse_args()
    engine = create_db_engine(args.database_url)
    SessionLocal = create_session_factory(engine)
    with SessionLocal() as db:
        package_ids = _target_package_ids(db, args.package_id, include_all=args.all)
        reports = [_audit_package(db, package_id) for package_id in package_ids]
    print(json.dumps({"packages": reports}, ensure_ascii=False, indent=2, default=_json_default))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit voucher source uniqueness and balance for monthly packages.")
    parser.add_argument("--database-url", help="SQLAlchemy database URL. Defaults to app settings.")
    parser.add_argument("--package-id", type=UUID, help="Monthly work package id to audit.")
    parser.add_argument("--all", action="store_true", help="Audit all packages.")
    args = parser.parse_args()
    if not args.package_id and not args.all:
        parser.error("Provide --package-id or --all.")
    return args


def _target_package_ids(db: Session, package_id: UUID | None, *, include_all: bool) -> list[UUID]:
    if package_id is not None:
        package = db.get(MonthlyWorkPackage, package_id)
        if package is None:
            raise SystemExit(f"Monthly work package not found: {package_id}")
        return [package.id]
    return list(
        db.scalars(select(MonthlyWorkPackage.id).order_by(MonthlyWorkPackage.period_year, MonthlyWorkPackage.period_month))
    )


def _audit_package(db: Session, package_id: UUID) -> dict:
    package = db.get(MonthlyWorkPackage, package_id)
    vouchers = db.scalars(
        select(Voucher)
        .options(selectinload(Voucher.entries))
        .where(Voucher.monthly_work_package_id == package_id)
        .order_by(Voucher.voucher_date, Voucher.created_at, Voucher.id)
    ).all()
    active_vouchers = [voucher for voucher in vouchers if voucher.status != "REJECTED"]
    bank_usage: dict[UUID, list[dict]] = defaultdict(list)
    invoice_usage: dict[UUID, list[dict]] = defaultdict(list)
    missing_source_group_type: list[dict] = []
    imbalanced: list[dict] = []

    for voucher in active_vouchers:
        debit_total = _entry_total(voucher.entries, "DEBIT")
        credit_total = _entry_total(voucher.entries, "CREDIT")
        if debit_total != credit_total:
            imbalanced.append(
                {
                    "voucher_id": voucher.id,
                    "voucher_number": voucher.voucher_number,
                    "status": voucher.status,
                    "debit_total": debit_total,
                    "credit_total": credit_total,
                    "difference": debit_total - credit_total,
                }
            )
        source_data = voucher.source_data or {}
        if not source_data.get("source_group_type"):
            missing_source_group_type.append(_voucher_ref(voucher))
        for bank_id in _source_uuid_list(source_data.get("bank_transaction_ids")) or _source_uuid_list(
            source_data.get("bank_transaction_id")
        ):
            bank_usage[bank_id].append(_voucher_ref(voucher))
        for invoice_id in _source_uuid_list(source_data.get("invoice_ids")) or _source_uuid_list(source_data.get("invoice_id")):
            invoice_usage[invoice_id].append(_voucher_ref(voucher))

    return {
        "package_id": package_id,
        "period_year": package.period_year,
        "period_month": package.period_month,
        "voucher_status_counts": dict(Counter(voucher.status for voucher in vouchers)),
        "active_voucher_count": len(active_vouchers),
        "imbalanced_vouchers": imbalanced,
        "duplicate_bank_sources": _duplicates(bank_usage),
        "duplicate_invoice_sources": _duplicates(invoice_usage),
        "missing_source_group_type_count": len(missing_source_group_type),
        "missing_source_group_type_examples": missing_source_group_type[:20],
    }


def _entry_total(entries: list[VoucherEntry], direction: str) -> Decimal:
    return sum((entry.amount for entry in entries if entry.direction == direction), Decimal("0.00"))


def _voucher_ref(voucher: Voucher) -> dict:
    return {
        "voucher_id": voucher.id,
        "voucher_number": voucher.voucher_number,
        "status": voucher.status,
        "summary": voucher.summary,
        "source_key": voucher.source_key,
    }


def _source_uuid_list(value) -> list[UUID]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    source_ids: list[UUID] = []
    for item in values:
        try:
            source_ids.append(item if isinstance(item, UUID) else UUID(str(item)))
        except (TypeError, ValueError):
            continue
    return source_ids


def _duplicates(usage: dict[UUID, list[dict]]) -> list[dict]:
    return [
        {"source_id": source_id, "voucher_count": len(vouchers), "vouchers": vouchers}
        for source_id, vouchers in sorted(usage.items(), key=lambda item: str(item[0]))
        if len(vouchers) > 1
    ]


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    return str(value)


if __name__ == "__main__":
    main()
