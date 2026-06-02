from __future__ import annotations

import hashlib
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.accounting.subjects import SMALL_BUSINESS_SUBJECTS
from app.core.org_context import get_current_organization_id
from app.models import (
    AccountSubject,
    AuditLog,
    BankTransaction,
    DEFAULT_CHANNEL_ID,
    Enterprise,
    Invoice,
    MatchRecord,
    MonthlyWorkPackage,
    Voucher,
    VoucherEntry,
    VoucherRule,
)


class VoucherDomainError(Exception):
    """Base exception for voucher domain errors."""


class VoucherValidationError(VoucherDomainError):
    pass


def ensure_enterprise_subjects(db: Session, *, enterprise_id: UUID) -> list[AccountSubject]:
    organization_id = get_current_organization_id()
    enterprise = db.get(Enterprise, enterprise_id)
    if enterprise is None or enterprise.organization_id != organization_id:
        raise VoucherDomainError("Enterprise not found in current organization.")

    existing_subjects = db.scalars(
        select(AccountSubject).where(
            AccountSubject.organization_id == organization_id,
            AccountSubject.enterprise_id == enterprise_id,
        )
    ).all()
    existing_codes = {subject.code for subject in existing_subjects}

    for subject_template in SMALL_BUSINESS_SUBJECTS:
        if subject_template["code"] in existing_codes:
            continue
        db.add(
            AccountSubject(
                channel_id=DEFAULT_CHANNEL_ID,
                organization_id=organization_id,
                enterprise_id=enterprise_id,
                **subject_template,
            )
        )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise VoucherDomainError("Enterprise account subjects could not be initialized.") from exc

    return db.scalars(
        select(AccountSubject)
        .where(
            AccountSubject.organization_id == organization_id,
            AccountSubject.enterprise_id == enterprise_id,
        )
        .order_by(AccountSubject.code)
    ).all()


def list_enterprise_subjects(db: Session, *, enterprise_id: UUID) -> list[AccountSubject]:
    ensure_enterprise_subjects(db, enterprise_id=enterprise_id)
    organization_id = get_current_organization_id()
    return db.scalars(
        select(AccountSubject)
        .where(
            AccountSubject.organization_id == organization_id,
            AccountSubject.enterprise_id == enterprise_id,
        )
        .order_by(AccountSubject.code)
    ).all()


def generate_voucher_drafts(db: Session, *, monthly_work_package_id: UUID) -> dict:
    organization_id = get_current_organization_id()
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None or package.organization_id != organization_id:
        raise VoucherDomainError("Monthly work package not found in current organization.")
    enterprise = db.get(Enterprise, package.enterprise_id)
    if enterprise is None or enterprise.organization_id != organization_id:
        raise VoucherDomainError("Enterprise not found.")

    subjects = ensure_enterprise_subjects(db, enterprise_id=enterprise.id)
    account_names = {subject.code: subject.name for subject in subjects}
    _refresh_existing_pending_single_bank_vouchers(db, package=package, account_names=account_names)

    created: list[Voucher] = []
    existing_source_keys = set(
        db.scalars(
            select(Voucher.source_key).where(
                Voucher.monthly_work_package_id == package.id,
            )
        )
    )

    created.extend(
        _generate_confirmed_match_vouchers(
            db,
            package=package,
            existing_source_keys=existing_source_keys,
            account_names=account_names,
        )
    )
    created.extend(
        _generate_bank_fee_vouchers(
            db,
            package=package,
            existing_source_keys=existing_source_keys,
            account_names=account_names,
        )
    )
    created.extend(
        _generate_unmatched_invoice_vouchers(
            db,
            package=package,
            existing_source_keys=existing_source_keys,
            account_names=account_names,
        )
    )
    created.extend(
        _generate_unmatched_bank_transaction_vouchers(
            db,
            package=package,
            existing_source_keys=existing_source_keys,
            account_names=account_names,
        )
    )

    for voucher in created:
        voucher.validation_errors = validate_voucher(db, voucher)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise VoucherDomainError("Voucher drafts could not be generated.") from exc

    for voucher in created:
        db.refresh(voucher)

    return {"created_vouchers": len(created), "vouchers": created}


def list_package_vouchers(db: Session, *, monthly_work_package_id: UUID) -> list[Voucher]:
    organization_id = get_current_organization_id()
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None or package.organization_id != organization_id:
        raise VoucherDomainError("Monthly work package not found in current organization.")

    vouchers = db.scalars(
        select(Voucher)
        .options(selectinload(Voucher.entries))
        .where(
            Voucher.organization_id == organization_id,
            Voucher.monthly_work_package_id == monthly_work_package_id,
        )
        .order_by(Voucher.voucher_date, Voucher.created_at, Voucher.id)
    ).all()
    return [_enrich_voucher_source_data(db, voucher) for voucher in vouchers]


def list_bank_ledger(db: Session, *, monthly_work_package_id: UUID) -> list[dict]:
    package = _get_package_for_operation(db, monthly_work_package_id=monthly_work_package_id)
    link_index = _voucher_source_link_index(db, package=package)
    match_index = _match_source_link_index(db, package=package)
    transactions = db.scalars(
        select(BankTransaction)
        .where(
            BankTransaction.organization_id == package.organization_id,
            BankTransaction.monthly_work_package_id == package.id,
        )
        .order_by(BankTransaction.transaction_date, BankTransaction.id)
    ).all()

    rows: list[dict] = []
    for transaction in transactions:
        linked_vouchers = link_index["bank"].get(transaction.id, [])
        linked_matches = match_index["bank"].get(transaction.id, [])
        voucher_status = _ledger_voucher_status(linked_vouchers)
        matching_status = "MATCHED" if linked_matches else "UNMATCHED"
        rows.append(
            {
                "id": transaction.id,
                "source_type": "BANK",
                "transaction_date": transaction.transaction_date,
                "summary": transaction.summary or "",
                "direction": _bank_transaction_direction(transaction),
                "direction_label": _bank_transaction_direction_label(transaction),
                "counterparty_name": transaction.counterparty_name or "",
                "debit_amount": _money(transaction.debit_amount or Decimal("0.00")),
                "credit_amount": _money(transaction.credit_amount or Decimal("0.00")),
                "transaction_amount": _transaction_amount(transaction),
                "balance": _money(transaction.balance) if transaction.balance is not None else None,
                "matching_status": matching_status,
                "matching_status_label": _matching_status_label(matching_status),
                "voucher_status": voucher_status,
                "voucher_status_label": _ledger_voucher_status_label(voucher_status),
                "linked_invoice_count": len({match.invoice_id for match in linked_matches if match.invoice_id}),
                "linked_voucher_count": len(linked_vouchers),
                "linked_voucher_numbers": _linked_voucher_numbers(linked_vouchers),
                "linked_vouchers": _linked_voucher_reads(linked_vouchers),
            }
        )
    return rows


def list_invoice_ledger(db: Session, *, monthly_work_package_id: UUID) -> list[dict]:
    package = _get_package_for_operation(db, monthly_work_package_id=monthly_work_package_id)
    link_index = _voucher_source_link_index(db, package=package)
    match_index = _match_source_link_index(db, package=package)
    invoices = db.scalars(
        select(Invoice)
        .where(
            Invoice.organization_id == package.organization_id,
            Invoice.monthly_work_package_id == package.id,
        )
        .order_by(Invoice.invoice_date, Invoice.id)
    ).all()

    rows: list[dict] = []
    for invoice in invoices:
        linked_vouchers = link_index["invoice"].get(invoice.id, [])
        linked_matches = match_index["invoice"].get(invoice.id, [])
        voucher_status = _ledger_voucher_status(linked_vouchers)
        matching_status = "MATCHED" if linked_matches else "UNMATCHED"
        rows.append(
            {
                "id": invoice.id,
                "source_type": "INVOICE",
                "invoice_direction": invoice.invoice_direction,
                "invoice_direction_label": _invoice_direction_label(invoice.invoice_direction),
                "invoice_number": invoice.invoice_number or "",
                "invoice_date": invoice.invoice_date,
                "counterparty_name": _invoice_counterparty(invoice),
                "counterparty_role": _invoice_counterparty_role(invoice),
                "amount": _money(invoice.amount),
                "tax_amount": _money(invoice.tax_amount),
                "total_amount": _money(invoice.total_amount),
                "matching_status": matching_status,
                "matching_status_label": _matching_status_label(matching_status),
                "voucher_status": voucher_status,
                "voucher_status_label": _ledger_voucher_status_label(voucher_status),
                "linked_bank_count": len({match.bank_transaction_id for match in linked_matches if match.bank_transaction_id}),
                "linked_voucher_count": len(linked_vouchers),
                "linked_voucher_numbers": _linked_voucher_numbers(linked_vouchers),
                "linked_vouchers": _linked_voucher_reads(linked_vouchers),
            }
        )
    return rows


def get_voucher_ledger_summary(db: Session, *, monthly_work_package_id: UUID) -> dict:
    package = _get_package_for_operation(db, monthly_work_package_id=monthly_work_package_id)
    bank_rows = list_bank_ledger(db, monthly_work_package_id=package.id)
    invoice_rows = list_invoice_ledger(db, monthly_work_package_id=package.id)
    vouchers = db.scalars(
        select(Voucher)
        .where(
            Voucher.organization_id == package.organization_id,
            Voucher.monthly_work_package_id == package.id,
            Voucher.status != "REJECTED",
        )
    ).all()
    single_source_total = Decimal("0.00")
    difference_total = Decimal("0.00")
    for voucher in vouchers:
        source_data = voucher.source_data or {}
        bank_ids = _source_uuid_list(source_data.get("bank_transaction_ids")) or _source_uuid_list(
            source_data.get("bank_transaction_id")
        )
        invoice_ids = _source_uuid_list(source_data.get("invoice_ids")) or _source_uuid_list(source_data.get("invoice_id"))
        if bool(bank_ids) ^ bool(invoice_ids):
            single_source_total += _voucher_gross_amount(voucher)
        difference_total += abs(_money(Decimal(str(source_data.get("difference_amount") or "0.00"))))

    return {
        "bank_total_count": len(bank_rows),
        "bank_processed_count": sum(1 for row in bank_rows if row["voucher_status"] != "UNPROCESSED"),
        "bank_pending_count": sum(1 for row in bank_rows if row["voucher_status"] == "UNPROCESSED"),
        "invoice_total_count": len(invoice_rows),
        "invoice_processed_count": sum(1 for row in invoice_rows if row["voucher_status"] != "UNPROCESSED"),
        "invoice_pending_count": sum(1 for row in invoice_rows if row["voucher_status"] == "UNPROCESSED"),
        "voucher_total_count": len(vouchers),
        "pending_task_count": sum(1 for voucher in vouchers if voucher.status == "PENDING_CONFIRMATION"),
        "difference_total_amount": _money(difference_total),
        "single_source_total_amount": _money(single_source_total),
    }


def confirm_voucher(db: Session, *, voucher_id: UUID, confirmed_by: str = "operator") -> Voucher:
    organization_id = get_current_organization_id()
    voucher = db.scalar(
        select(Voucher)
        .options(selectinload(Voucher.entries))
        .where(
            Voucher.id == voucher_id,
            Voucher.organization_id == organization_id,
        )
    )
    if voucher is None:
        raise VoucherDomainError("Voucher not found in current organization.")

    validation_errors = validate_voucher(db, voucher)
    if validation_errors:
        voucher.validation_errors = validation_errors
        raise VoucherValidationError(", ".join(validation_errors))

    before_data = {
        "status": voucher.status,
        "voucher_number": voucher.voucher_number,
        "confirmed_by": voucher.confirmed_by,
        "confirmed_at": voucher.confirmed_at.isoformat() if voucher.confirmed_at else None,
    }
    if not voucher.voucher_number:
        voucher.voucher_number = _next_voucher_number(db, monthly_work_package_id=voucher.monthly_work_package_id)
    voucher.status = "CONFIRMED"
    voucher.confirmed_by = confirmed_by
    voucher.confirmed_at = datetime.utcnow()
    voucher.validation_errors = []
    db.add(
        AuditLog(
            channel_id=DEFAULT_CHANNEL_ID,
            organization_id=voucher.organization_id,
            monthly_work_package_id=voucher.monthly_work_package_id,
            actor=confirmed_by,
            action="CONFIRM_VOUCHER",
            before_data=before_data,
            after_data={
                "status": voucher.status,
                "voucher_number": voucher.voucher_number,
                "confirmed_by": voucher.confirmed_by,
                "confirmed_at": voucher.confirmed_at.isoformat(),
            },
        )
    )

    db.commit()
    db.refresh(voucher)
    confirmed_voucher = db.scalar(
        select(Voucher)
        .options(selectinload(Voucher.entries))
        .where(Voucher.id == voucher.id)
    )
    return _enrich_voucher_source_data(db, confirmed_voucher)


def reject_voucher(db: Session, *, voucher_id: UUID, rejected_by: str = "operator", reason: str = "") -> Voucher:
    organization_id = get_current_organization_id()
    voucher = db.scalar(
        select(Voucher)
        .options(selectinload(Voucher.entries))
        .where(
            Voucher.id == voucher_id,
            Voucher.organization_id == organization_id,
        )
    )
    if voucher is None:
        raise VoucherDomainError("Voucher not found in current organization.")

    before_data = {
        "status": voucher.status,
        "voucher_number": voucher.voucher_number,
        "confirmed_by": voucher.confirmed_by,
        "confirmed_at": voucher.confirmed_at.isoformat() if voucher.confirmed_at else None,
        "validation_errors": voucher.validation_errors or [],
    }
    rejection_errors = list(voucher.validation_errors or [])
    _append_once(rejection_errors, "OPERATOR_REJECTED")
    voucher.status = "REJECTED"
    voucher.confirmed_by = rejected_by
    voucher.confirmed_at = datetime.utcnow()
    voucher.validation_errors = rejection_errors
    source_data = dict(voucher.source_data or {})
    if reason:
        source_data["rejection_reason"] = reason
    voucher.source_data = source_data
    db.add(
        AuditLog(
            channel_id=DEFAULT_CHANNEL_ID,
            organization_id=voucher.organization_id,
            monthly_work_package_id=voucher.monthly_work_package_id,
            actor=rejected_by,
            action="REJECT_VOUCHER",
            before_data=before_data,
            after_data={
                "status": voucher.status,
                "voucher_number": voucher.voucher_number,
                "confirmed_by": voucher.confirmed_by,
                "confirmed_at": voucher.confirmed_at.isoformat(),
                "validation_errors": voucher.validation_errors,
                "reason": reason,
            },
        )
    )
    db.commit()
    db.refresh(voucher)
    rejected_voucher = db.scalar(
        select(Voucher)
        .options(selectinload(Voucher.entries))
        .where(Voucher.id == voucher.id)
    )
    return _enrich_voucher_source_data(db, rejected_voucher)


def reopen_voucher(db: Session, *, voucher_id: UUID, reopened_by: str = "operator", reason: str = "") -> Voucher:
    voucher = _get_voucher_for_operation(db, voucher_id=voucher_id)
    before_data = {
        "status": voucher.status,
        "voucher_number": voucher.voucher_number,
        "confirmed_by": voucher.confirmed_by,
        "confirmed_at": voucher.confirmed_at.isoformat() if voucher.confirmed_at else None,
        "validation_errors": voucher.validation_errors or [],
    }

    source_data = dict(voucher.source_data or {})
    if reason:
        source_data["reopen_reason"] = reason

    voucher.status = "PENDING_CONFIRMATION"
    voucher.voucher_number = None
    voucher.confirmed_by = None
    voucher.confirmed_at = None
    voucher.source_data = source_data
    voucher.validation_errors = [error for error in validate_voucher(db, voucher) if error != "OPERATOR_REJECTED"]
    db.add(
        AuditLog(
            channel_id=DEFAULT_CHANNEL_ID,
            organization_id=voucher.organization_id,
            monthly_work_package_id=voucher.monthly_work_package_id,
            actor=reopened_by,
            action="REOPEN_VOUCHER",
            before_data=before_data,
            after_data={
                "status": voucher.status,
                "voucher_number": voucher.voucher_number,
                "confirmed_by": voucher.confirmed_by,
                "confirmed_at": None,
                "validation_errors": voucher.validation_errors,
                "reason": reason,
            },
        )
    )
    db.commit()
    reopened_voucher = db.scalar(
        select(Voucher)
        .options(selectinload(Voucher.entries))
        .where(Voucher.id == voucher.id)
    )
    return _enrich_voucher_source_data(db, reopened_voucher)


def list_voucher_rematch_candidates(db: Session, *, voucher_id: UUID) -> dict:
    voucher = _get_voucher_for_operation(db, voucher_id=voucher_id)
    package = db.get(MonthlyWorkPackage, voucher.monthly_work_package_id)
    if package is None:
        raise VoucherDomainError("Monthly work package not found.")

    source_data = dict(voucher.source_data or {})
    current_bank_id = _source_uuid(source_data.get("bank_transaction_id"))
    current_invoice_id = _source_uuid(source_data.get("invoice_id"))
    used_source_ids = _used_non_rejected_voucher_source_ids(db, package_id=package.id, exclude_voucher_id=voucher.id)

    bank_transaction = (
        _get_package_source(db, BankTransaction, current_bank_id, voucher.organization_id, package.id)
        if current_bank_id
        else None
    )
    invoice = (
        _get_package_source(db, Invoice, current_invoice_id, voucher.organization_id, package.id)
        if current_invoice_id
        else None
    )

    invoice_candidates = []
    if bank_transaction is not None:
        invoices = db.scalars(
            select(Invoice)
            .where(
                Invoice.organization_id == voucher.organization_id,
                Invoice.monthly_work_package_id == package.id,
            )
            .order_by(Invoice.invoice_date, Invoice.id)
        ).all()
        invoice_candidates = [
            _invoice_rematch_candidate(
                item,
                bank_transaction,
                is_current=item.id == current_invoice_id,
                used_by_status=used_source_ids["invoice_ids"].get(item.id),
            )
            for item in invoices
        ]

    bank_candidates = []
    if invoice is not None:
        transactions = db.scalars(
            select(BankTransaction)
            .where(
                BankTransaction.organization_id == voucher.organization_id,
                BankTransaction.monthly_work_package_id == package.id,
            )
            .order_by(BankTransaction.transaction_date, BankTransaction.id)
        ).all()
        bank_candidates = [
            _bank_rematch_candidate(
                item,
                invoice,
                is_current=item.id == current_bank_id,
                used_by_status=used_source_ids["bank_transaction_ids"].get(item.id),
            )
            for item in transactions
        ]

    return {
        "current_bank_transaction_id": current_bank_id,
        "current_invoice_id": current_invoice_id,
        "bank_candidates": sorted(bank_candidates, key=lambda item: (-item["score"], item["date"] or date.min))[:50],
        "invoice_candidates": sorted(invoice_candidates, key=lambda item: (-item["score"], item["date"] or date.min))[:50],
    }


def rematch_voucher(
    db: Session,
    *,
    voucher_id: UUID,
    bank_transaction_id: UUID | None = None,
    invoice_id: UUID | None = None,
    bank_transaction_ids: list[UUID] | None = None,
    invoice_ids: list[UUID] | None = None,
) -> Voucher:
    voucher = _get_voucher_for_operation(db, voucher_id=voucher_id)
    package = db.get(MonthlyWorkPackage, voucher.monthly_work_package_id)
    if package is None:
        raise VoucherDomainError("Monthly work package not found.")

    source_data = dict(voucher.source_data or {})
    next_bank_ids = _rematch_source_ids(
        explicit_ids=bank_transaction_ids,
        explicit_id=bank_transaction_id,
        source_ids=source_data.get("bank_transaction_ids"),
        source_id=source_data.get("bank_transaction_id"),
    )
    next_invoice_ids = _rematch_source_ids(
        explicit_ids=invoice_ids,
        explicit_id=invoice_id,
        source_ids=source_data.get("invoice_ids"),
        source_id=source_data.get("invoice_id"),
    )
    if not next_bank_ids or not next_invoice_ids:
        raise VoucherValidationError("BANK_TRANSACTION_AND_INVOICE_REQUIRED")
    if len(next_bank_ids) > 1 and len(next_invoice_ids) > 1:
        raise VoucherValidationError("MANY_TO_MANY_REMAP_UNSUPPORTED")

    transactions = [
        _get_package_source(db, BankTransaction, source_id, voucher.organization_id, package.id)
        for source_id in next_bank_ids
    ]
    invoices = [
        _get_package_source(db, Invoice, source_id, voucher.organization_id, package.id)
        for source_id in next_invoice_ids
    ]
    if any(item is None for item in transactions) or any(item is None for item in invoices):
        raise VoucherDomainError("Rematch source not found in current package.")
    transactions = [item for item in transactions if item is not None]
    invoices = [item for item in invoices if item is not None]
    used_source_ids = _used_non_rejected_voucher_source_ids(db, package_id=package.id, exclude_voucher_id=voucher.id)
    if any(source_id in used_source_ids["bank_transaction_ids"] for source_id in next_bank_ids) or any(
        source_id in used_source_ids["invoice_ids"] for source_id in next_invoice_ids
    ):
        raise VoucherValidationError("SOURCE_ALREADY_USED")
    _retire_single_source_vouchers(
        db,
        package_id=package.id,
        exclude_voucher_id=voucher.id,
        bank_transaction_ids=next_bank_ids,
        invoice_ids=next_invoice_ids,
    )

    for old_match_id in _source_uuid_list(source_data.get("match_record_ids")) or _source_uuid_list(source_data.get("match_record_id")):
        old_match = _get_package_source(db, MatchRecord, old_match_id, voucher.organization_id, package.id)
        if old_match is not None and old_match.confirmation_status != "REJECTED":
            old_match.confirmation_status = "REJECTED"

    match_group: list[tuple[MatchRecord, BankTransaction, Invoice]] = []
    for transaction in transactions:
        for invoice in invoices:
            match = MatchRecord(
                channel_id=DEFAULT_CHANNEL_ID,
                organization_id=voucher.organization_id,
                monthly_work_package_id=package.id,
                bank_transaction_id=transaction.id,
                invoice_id=invoice.id,
                match_method="MANUAL_REMAP",
                confidence=90,
                explanation="人工重新选择匹配对象",
                confirmation_status="CONFIRMED",
            )
            db.add(match)
            db.flush()
            match_group.append((match, transaction, invoice))

    subjects = ensure_enterprise_subjects(db, enterprise_id=package.enterprise_id)
    account_names = {subject.code: subject.name for subject in subjects}
    if len(transactions) == 1 and len(invoices) == 1:
        transaction = transactions[0]
        invoice = invoices[0]
        source_key = f"match:{match_group[0][0].id}"
        source_data_after = _source_data_for_match(match_group[0][0], transaction, invoice)
        voucher_date = transaction.transaction_date
        source_type = "MATCH_RECORD"
        source_id = str(match_group[0][0].id)
    elif len(transactions) > 1:
        invoice = invoices[0]
        transaction_total = sum((_transaction_amount(transaction) for transaction in transactions), Decimal("0.00"))
        if _money(transaction_total) != _money(invoice.total_amount):
            raise VoucherValidationError("REMATCH_AMOUNT_NOT_BALANCED")
        source_key = _composite_source_key(
            "one-invoice-multiple-bank",
            bank_transaction_ids=[transaction.id for transaction in transactions],
            invoice_ids=[invoice.id],
        )
        source_data_after = _source_data_for_one_invoice_multiple_bank_group(match_group, source_key)
        voucher_date = max(transaction.transaction_date for transaction in transactions)
        source_type = "MATCH_GROUP"
        source_id = source_key
    else:
        transaction = transactions[0]
        invoice_directions = {invoice.invoice_direction for invoice in invoices}
        if len(invoice_directions) != 1:
            raise VoucherValidationError("REMATCH_INVOICE_DIRECTIONS_MIXED")
        invoice_total = sum((_money(invoice.total_amount) for invoice in invoices), Decimal("0.00"))
        if _money(invoice_total) != _transaction_amount(transaction):
            raise VoucherValidationError("REMATCH_AMOUNT_NOT_BALANCED")
        source_key = _composite_source_key(
            "one-bank-multiple-invoices",
            bank_transaction_ids=[transaction.id],
            invoice_ids=[invoice.id for invoice in invoices],
        )
        source_data_after = _source_data_for_one_bank_multiple_invoice_group(match_group, source_key)
        voucher_date = transaction.transaction_date
        source_type = "MATCH_GROUP"
        source_id = source_key

    invoice_direction = invoices[0].invoice_direction
    if invoice_direction == "OUTPUT" and len(invoices) == 1:
        summary = "确认销售收入并收款"
        lines = _output_invoice_lines(invoices[0])
        ai_confidence = 90
        ai_reason = "人工重新匹配销项发票与银行收款"
    elif invoice_direction == "OUTPUT":
        summary = "确认多张销售发票并收款"
        lines = _combined_output_invoice_lines(transactions[0], invoices)
        ai_confidence = 90
        ai_reason = "人工重新匹配多张销项发票与银行收款"
    elif invoice_direction == "INPUT" and len(invoices) == 1:
        summary = "确认费用并付款"
        lines = _input_invoice_lines(invoices[0])
        ai_confidence = 86
        ai_reason = "人工重新匹配进项发票与银行付款"
        if len(transactions) > 1:
            summary = "确认费用并分次付款"
            ai_reason = "人工重新匹配一张进项发票与多笔银行付款"
    elif invoice_direction == "INPUT":
        summary = "确认多张费用发票并付款"
        lines = _combined_input_invoice_lines(transactions[0], invoices)
        ai_confidence = 86
        ai_reason = "人工重新匹配多张进项发票与银行付款"
    else:
        raise VoucherValidationError("UNSUPPORTED_INVOICE_DIRECTION")

    before_data = {
        "status": voucher.status,
        "source_key": voucher.source_key,
        "source_data": source_data,
        "voucher_number": voucher.voucher_number,
        "validation_errors": voucher.validation_errors or [],
    }
    voucher.voucher_date = voucher_date
    voucher.voucher_number = None
    voucher.summary = summary
    voucher.source_key = source_key
    voucher.source_data = source_data_after
    voucher.status = "PENDING_CONFIRMATION"
    voucher.ai_confidence = ai_confidence
    voucher.ai_reason = ai_reason
    voucher.confirmed_by = None
    voucher.confirmed_at = None
    voucher.entries = [
        VoucherEntry(
            channel_id=DEFAULT_CHANNEL_ID,
            organization_id=package.organization_id,
            line_no=index,
            direction=direction,
            account_code=account_code,
            account_name=account_names.get(account_code, ""),
            amount=_money(amount),
            source_type=source_type,
            source_id=source_id,
        )
        for index, (direction, account_code, amount) in enumerate(lines, start=1)
    ]
    voucher.validation_errors = validate_voucher(db, voucher)
    db.add(
        AuditLog(
            channel_id=DEFAULT_CHANNEL_ID,
            organization_id=voucher.organization_id,
            monthly_work_package_id=voucher.monthly_work_package_id,
            actor="operator",
            action="REMATCH_VOUCHER",
            before_data=before_data,
            after_data={
                "status": voucher.status,
                "source_key": voucher.source_key,
                "source_data": voucher.source_data,
                "validation_errors": voucher.validation_errors,
            },
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise VoucherDomainError("Voucher rematch could not be saved.") from exc

    rematched_voucher = db.scalar(
        select(Voucher)
        .options(selectinload(Voucher.entries))
        .where(Voucher.id == voucher.id)
    )
    return _enrich_voucher_source_data(db, rematched_voucher)


def update_single_source_voucher_treatment(
    db: Session,
    *,
    voucher_id: UUID,
    treatment_type: str,
    summary: str,
    debit_account_code: str,
    credit_account_code: str,
    note: str = "",
) -> Voucher:
    voucher = _get_voucher_for_operation(db, voucher_id=voucher_id)
    package = db.get(MonthlyWorkPackage, voucher.monthly_work_package_id)
    if package is None:
        raise VoucherDomainError("Monthly work package not found.")

    source_data = dict(voucher.source_data or {})
    bank_transaction_id = _source_uuid(source_data.get("bank_transaction_id"))
    invoice_id = _source_uuid(source_data.get("invoice_id"))
    if (bank_transaction_id is None and invoice_id is None) or (bank_transaction_id is not None and invoice_id is not None):
        raise VoucherValidationError("SINGLE_SOURCE_VOUCHER_REQUIRED")

    if not summary.strip():
        raise VoucherValidationError("SUMMARY_REQUIRED")

    subjects = ensure_enterprise_subjects(db, enterprise_id=package.enterprise_id)
    subject_by_code = {subject.code: subject for subject in subjects}
    debit_subject = subject_by_code.get(debit_account_code)
    credit_subject = subject_by_code.get(credit_account_code)
    if debit_subject is None or credit_subject is None:
        raise VoucherValidationError("SUBJECT_NOT_FOUND")
    if not debit_subject.is_enabled or not credit_subject.is_enabled:
        raise VoucherValidationError("SUBJECT_NOT_ENABLED")
    if not debit_subject.is_leaf or not credit_subject.is_leaf:
        raise VoucherValidationError("SUBJECT_NOT_LEAF")

    amount = _single_source_voucher_amount(db, package=package, bank_transaction_id=bank_transaction_id, invoice_id=invoice_id)
    if amount == Decimal("0.00"):
        raise VoucherValidationError("ZERO_AMOUNT")

    before_data = {
        "summary": voucher.summary,
        "source_data": source_data,
        "entries": [
            {
                "direction": entry.direction,
                "account_code": entry.account_code,
                "account_name": entry.account_name,
                "amount": str(entry.amount),
            }
            for entry in voucher.entries
        ],
    }
    treatment = {
        "treatment_type": treatment_type.strip(),
        "summary": summary.strip(),
        "debit_account_code": debit_subject.code,
        "debit_account_name": debit_subject.name,
        "credit_account_code": credit_subject.code,
        "credit_account_name": credit_subject.name,
        "note": note.strip(),
    }
    source_data["accounting_treatment"] = treatment
    voucher.summary = summary.strip()
    voucher.source_data = source_data
    voucher.status = "PENDING_CONFIRMATION"
    voucher.voucher_number = None
    voucher.confirmed_by = None
    voucher.confirmed_at = None
    voucher.ai_reason = f"{treatment['treatment_type']}：{treatment['note'] or '人工调整单边凭证会计处理'}"
    voucher.entries = [
        VoucherEntry(
            channel_id=DEFAULT_CHANNEL_ID,
            organization_id=package.organization_id,
            line_no=1,
            direction="DEBIT",
            account_code=debit_subject.code,
            account_name=debit_subject.name,
            amount=amount,
            source_type="ACCOUNTING_TREATMENT",
            source_id=str(voucher.id),
        ),
        VoucherEntry(
            channel_id=DEFAULT_CHANNEL_ID,
            organization_id=package.organization_id,
            line_no=2,
            direction="CREDIT",
            account_code=credit_subject.code,
            account_name=credit_subject.name,
            amount=amount,
            source_type="ACCOUNTING_TREATMENT",
            source_id=str(voucher.id),
        ),
    ]
    voucher.validation_errors = validate_voucher(db, voucher)
    _record_voucher_rule_from_user_edit(
        db,
        package=package,
        voucher=voucher,
        treatment=treatment,
        bank_transaction_id=bank_transaction_id,
        invoice_id=invoice_id,
    )
    db.add(
        AuditLog(
            channel_id=DEFAULT_CHANNEL_ID,
            organization_id=voucher.organization_id,
            monthly_work_package_id=voucher.monthly_work_package_id,
            actor="operator",
            action="ADJUST_SINGLE_SOURCE_VOUCHER_TREATMENT",
            before_data=before_data,
            after_data={
                "summary": voucher.summary,
                "source_data": voucher.source_data,
                "validation_errors": voucher.validation_errors,
            },
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise VoucherDomainError("Voucher treatment adjustment could not be saved.") from exc

    adjusted_voucher = db.scalar(
        select(Voucher)
        .options(selectinload(Voucher.entries))
        .where(Voucher.id == voucher.id)
    )
    return _enrich_voucher_source_data(db, adjusted_voucher)


def validate_voucher(db: Session, voucher: Voucher) -> list[str]:
    errors: list[str] = []
    package = db.get(MonthlyWorkPackage, voucher.monthly_work_package_id)
    debit_total = sum(
        (_money(entry.amount) for entry in voucher.entries if entry.direction == "DEBIT"),
        Decimal("0.00"),
    )
    credit_total = sum(
        (_money(entry.amount) for entry in voucher.entries if entry.direction == "CREDIT"),
        Decimal("0.00"),
    )
    if debit_total != credit_total:
        errors.append("DEBIT_CREDIT_NOT_EQUAL")

    if any(_money(entry.amount) <= Decimal("0.00") for entry in voucher.entries):
        errors.append("ZERO_AMOUNT")

    subjects_by_code = {}
    if package is not None:
        subjects_by_code = {
            subject.code: subject
            for subject in db.scalars(
                select(AccountSubject).where(
                    AccountSubject.organization_id == voucher.organization_id,
                    AccountSubject.enterprise_id == package.enterprise_id,
                )
            )
        }
    for entry in voucher.entries:
        subject = subjects_by_code.get(entry.account_code)
        if subject is None or not subject.is_enabled or not subject.allow_voucher:
            _append_once(errors, "SUBJECT_NOT_ENABLED")
        if subject is None or not subject.is_leaf:
            _append_once(errors, "SUBJECT_NOT_LEAF")

    if package is None or not _date_in_period(voucher.voucher_date, year=package.period_year, month=package.period_month):
        errors.append("DATE_OUT_OF_PERIOD")

    return errors


def _generate_confirmed_match_vouchers(
    db: Session,
    *,
    package: MonthlyWorkPackage,
    existing_source_keys: set[str],
    account_names: dict[str, str],
) -> list[Voucher]:
    created: list[Voucher] = []
    matches = db.execute(
        select(MatchRecord, BankTransaction, Invoice)
        .join(BankTransaction, BankTransaction.id == MatchRecord.bank_transaction_id)
        .join(Invoice, Invoice.id == MatchRecord.invoice_id)
        .where(
            MatchRecord.organization_id == package.organization_id,
            MatchRecord.monthly_work_package_id == package.id,
            BankTransaction.organization_id == package.organization_id,
            BankTransaction.monthly_work_package_id == package.id,
            Invoice.organization_id == package.organization_id,
            Invoice.monthly_work_package_id == package.id,
            MatchRecord.confirmation_status.in_(("AUTO_CONFIRMED", "CONFIRMED")),
        )
        .order_by(MatchRecord.created_at, MatchRecord.id)
    ).all()

    consumed_match_ids: set[UUID] = set()
    created.extend(
        _generate_one_invoice_multiple_bank_vouchers(
            db=db,
            package=package,
            matches=matches,
            existing_source_keys=existing_source_keys,
            account_names=account_names,
            consumed_match_ids=consumed_match_ids,
        )
    )
    created.extend(
        _generate_one_bank_multiple_invoice_vouchers(
            db=db,
            package=package,
            matches=matches,
            existing_source_keys=existing_source_keys,
            account_names=account_names,
            consumed_match_ids=consumed_match_ids,
        )
    )

    for match, transaction, invoice in matches:
        if match.id in consumed_match_ids:
            continue
        source_key = f"match:{match.id}"
        if source_key in existing_source_keys:
            continue

        has_difference = _transaction_amount(transaction) != _money(invoice.total_amount)
        if invoice.invoice_direction == "OUTPUT" and has_difference:
            voucher = _build_voucher(
                package=package,
                voucher_date=transaction.transaction_date,
                summary="确认销售收入并补齐差额",
                source_type="MATCH_RECORD",
                source_id=str(match.id),
                source_key=source_key,
                source_data=_source_data_for_match(match, transaction, invoice, force_task_type="DIFFERENCE_COMPLETION"),
                ai_confidence=min(match.confidence, 76),
                ai_reason="销项发票与银行收款金额不一致，系统补齐差额待人工确认",
                account_names=account_names,
                lines=_output_invoice_difference_lines(transaction, invoice),
            )
        elif invoice.invoice_direction == "OUTPUT":
            voucher = _build_voucher(
                package=package,
                voucher_date=transaction.transaction_date,
                summary="确认销售收入并收款",
                source_type="MATCH_RECORD",
                source_id=str(match.id),
                source_key=source_key,
                source_data=_source_data_for_match(match, transaction, invoice),
                ai_confidence=92,
                ai_reason="销项发票与银行收款已确认匹配",
                account_names=account_names,
                lines=_output_invoice_lines(invoice),
            )
        elif invoice.invoice_direction == "INPUT" and has_difference:
            voucher = _build_voucher(
                package=package,
                voucher_date=transaction.transaction_date,
                summary="确认费用并补齐差额",
                source_type="MATCH_RECORD",
                source_id=str(match.id),
                source_key=source_key,
                source_data=_source_data_for_match(match, transaction, invoice, force_task_type="DIFFERENCE_COMPLETION"),
                ai_confidence=min(match.confidence, 76),
                ai_reason="进项发票与银行付款金额不一致，系统补齐差额待人工确认",
                account_names=account_names,
                lines=_input_invoice_difference_lines(transaction, invoice),
            )
        elif invoice.invoice_direction == "INPUT":
            voucher = _build_voucher(
                package=package,
                voucher_date=transaction.transaction_date,
                summary="确认费用并付款",
                source_type="MATCH_RECORD",
                source_id=str(match.id),
                source_key=source_key,
                source_data=_source_data_for_match(match, transaction, invoice),
                ai_confidence=82,
                ai_reason="进项发票与银行付款已确认匹配",
                account_names=account_names,
                lines=_input_invoice_lines(invoice),
            )
        else:
            continue

        db.add(voucher)
        db.flush()
        existing_source_keys.add(source_key)
        created.append(voucher)

    return created


def _generate_one_invoice_multiple_bank_vouchers(
    *,
    db: Session,
    package: MonthlyWorkPackage,
    matches: list[tuple[MatchRecord, BankTransaction, Invoice]],
    existing_source_keys: set[str],
    account_names: dict[str, str],
    consumed_match_ids: set[UUID],
) -> list[Voucher]:
    created: list[Voucher] = []
    matches_by_invoice: dict[UUID, list[tuple[MatchRecord, BankTransaction, Invoice]]] = {}
    for match, transaction, invoice in matches:
        if match.id in consumed_match_ids:
            continue
        matches_by_invoice.setdefault(invoice.id, []).append((match, transaction, invoice))

    for invoice_id, group in matches_by_invoice.items():
        transactions_by_id = {transaction.id: transaction for _, transaction, _ in group}
        if len(transactions_by_id) <= 1:
            continue
        invoice = group[0][2]
        transaction_total = sum((_transaction_amount(transaction) for transaction in transactions_by_id.values()), Decimal("0.00"))
        if _money(transaction_total) != _money(invoice.total_amount):
            continue

        transaction_ids = sorted(transactions_by_id)
        match_ids = [match.id for match, _, _ in group]
        source_key = _composite_source_key(
            "one-invoice-multiple-bank",
            bank_transaction_ids=transaction_ids,
            invoice_ids=[invoice_id],
        )
        consumed_match_ids.update(match_ids)
        if source_key in existing_source_keys:
            continue

        if invoice.invoice_direction == "INPUT":
            summary = "确认费用并分次付款"
            lines = _input_invoice_lines(invoice)
            ai_confidence = min(match.confidence for match, _, _ in group)
            ai_reason = "一张进项发票由多笔银行付款合计匹配"
        elif invoice.invoice_direction == "OUTPUT":
            summary = "确认销售收入并分次收款"
            lines = _output_invoice_lines(invoice)
            ai_confidence = min(match.confidence for match, _, _ in group)
            ai_reason = "一张销项发票由多笔银行收款合计匹配"
        else:
            continue

        voucher = _build_voucher(
            package=package,
            voucher_date=max(transaction.transaction_date for transaction in transactions_by_id.values()),
            summary=summary,
            source_type="MATCH_GROUP",
            source_id=source_key,
            source_key=source_key,
            source_data=_source_data_for_one_invoice_multiple_bank_group(group, source_key),
            ai_confidence=ai_confidence,
            ai_reason=ai_reason,
            account_names=account_names,
            lines=lines,
        )
        db.add(voucher)
        db.flush()
        created.append(voucher)
        existing_source_keys.add(source_key)

    return created


def _generate_one_bank_multiple_invoice_vouchers(
    *,
    db: Session,
    package: MonthlyWorkPackage,
    matches: list[tuple[MatchRecord, BankTransaction, Invoice]],
    existing_source_keys: set[str],
    account_names: dict[str, str],
    consumed_match_ids: set[UUID],
) -> list[Voucher]:
    created: list[Voucher] = []
    matches_by_transaction: dict[UUID, list[tuple[MatchRecord, BankTransaction, Invoice]]] = {}
    for match, transaction, invoice in matches:
        if match.id in consumed_match_ids:
            continue
        matches_by_transaction.setdefault(transaction.id, []).append((match, transaction, invoice))

    for transaction_id, group in matches_by_transaction.items():
        invoices_by_id = {invoice.id: invoice for _, _, invoice in group}
        if len(invoices_by_id) <= 1:
            continue
        transaction = group[0][1]
        invoice_directions = {invoice.invoice_direction for invoice in invoices_by_id.values()}
        if len(invoice_directions) != 1:
            continue
        invoice_total = sum((_money(invoice.total_amount) for invoice in invoices_by_id.values()), Decimal("0.00"))
        has_difference = _money(invoice_total) != _transaction_amount(transaction)

        invoice_ids = sorted(invoices_by_id)
        match_ids = [match.id for match, _, _ in group]
        source_key = _composite_source_key(
            "one-bank-multiple-invoices",
            bank_transaction_ids=[transaction_id],
            invoice_ids=invoice_ids,
        )
        consumed_match_ids.update(match_ids)
        if source_key in existing_source_keys:
            continue

        direction = next(iter(invoice_directions))
        invoices = [invoices_by_id[invoice_id] for invoice_id in invoice_ids]
        if direction == "OUTPUT":
            summary = "确认多张销售发票并补齐收款差额" if has_difference else "确认多张销售发票并收款"
            lines = _combined_output_invoice_lines(transaction, invoices)
            ai_confidence = min(match.confidence for match, _, _ in group)
            ai_reason = "一笔银行收款对应多张销项发票，金额存在差额需人工确认" if has_difference else "一笔银行收款由多张销项发票合计匹配"
        elif direction == "INPUT":
            summary = "确认多张费用发票并补齐付款差额" if has_difference else "确认多张费用发票并付款"
            lines = _combined_input_invoice_lines(transaction, invoices)
            ai_confidence = min(match.confidence for match, _, _ in group)
            ai_reason = "一笔银行付款对应多张进项发票，金额存在差额需人工确认" if has_difference else "一笔银行付款由多张进项发票合计匹配"
        else:
            continue

        voucher = _build_voucher(
            package=package,
            voucher_date=transaction.transaction_date,
            summary=summary,
            source_type="MATCH_GROUP",
            source_id=source_key,
            source_key=source_key,
            source_data=_source_data_for_one_bank_multiple_invoice_group(group, source_key),
            ai_confidence=ai_confidence,
            ai_reason=ai_reason,
            account_names=account_names,
            lines=lines,
        )
        db.add(voucher)
        db.flush()
        created.append(voucher)
        existing_source_keys.add(source_key)

    return created


def _generate_bank_fee_vouchers(
    db: Session,
    *,
    package: MonthlyWorkPackage,
    existing_source_keys: set[str],
    account_names: dict[str, str],
) -> list[Voucher]:
    created: list[Voucher] = []
    matched_transaction_ids = _valid_matched_transaction_ids(db, package=package)
    transactions = db.scalars(
        select(BankTransaction)
        .where(
            BankTransaction.organization_id == package.organization_id,
            BankTransaction.monthly_work_package_id == package.id,
            BankTransaction.summary.contains("手续费"),
        )
        .order_by(BankTransaction.transaction_date, BankTransaction.id)
    ).all()

    for transaction in transactions:
        if transaction.id in matched_transaction_ids:
            continue
        source_key = f"bank:{transaction.id}"
        if source_key in existing_source_keys:
            continue

        voucher = _build_voucher(
            package=package,
            voucher_date=transaction.transaction_date,
            summary="支付银行手续费",
            source_type="BANK_TRANSACTION",
            source_id=str(transaction.id),
            source_key=source_key,
            source_data=_source_data_for_bank_transaction(transaction),
            ai_confidence=88,
            ai_reason="银行流水摘要包含手续费",
            account_names=account_names,
            lines=[
                ("DEBIT", "560301", _transaction_amount(transaction)),
                ("CREDIT", "1002", _transaction_amount(transaction)),
            ],
        )
        db.add(voucher)
        db.flush()
        existing_source_keys.add(source_key)
        created.append(voucher)

    return created


def _generate_unmatched_invoice_vouchers(
    db: Session,
    *,
    package: MonthlyWorkPackage,
    existing_source_keys: set[str],
    account_names: dict[str, str],
) -> list[Voucher]:
    created: list[Voucher] = []
    matched_invoice_ids = _valid_matched_invoice_ids(db, package=package)
    invoices = db.scalars(
        select(Invoice)
        .where(
            Invoice.organization_id == package.organization_id,
            Invoice.monthly_work_package_id == package.id,
        )
        .order_by(Invoice.invoice_date, Invoice.id)
    ).all()

    for invoice in invoices:
        if invoice.id in matched_invoice_ids:
            continue
        source_key = f"invoice:{invoice.id}"
        if source_key in existing_source_keys:
            continue

        if invoice.invoice_direction == "OUTPUT":
            voucher = _build_voucher(
                package=package,
                voucher_date=invoice.invoice_date,
                summary="确认销售收入未收款",
                source_type="INVOICE",
                source_id=str(invoice.id),
                source_key=source_key,
                source_data=_source_data_for_invoice(invoice),
                ai_confidence=68,
                ai_reason="销项发票暂无匹配银行流水，需人工确认是否已收款或挂应收账款",
                account_names=account_names,
                lines=_output_invoice_accrual_lines(invoice),
            )
        elif invoice.invoice_direction == "INPUT":
            voucher = _build_voucher(
                package=package,
                voucher_date=invoice.invoice_date,
                summary="确认费用未付款",
                source_type="INVOICE",
                source_id=str(invoice.id),
                source_key=source_key,
                source_data=_source_data_for_invoice(invoice),
                ai_confidence=62,
                ai_reason="进项发票暂无匹配银行流水，需人工确认是否已付款或挂应付账款",
                account_names=account_names,
                lines=_input_invoice_accrual_lines(invoice),
            )
        else:
            continue

        db.add(voucher)
        db.flush()
        existing_source_keys.add(source_key)
        created.append(voucher)

    return created


def _generate_unmatched_bank_transaction_vouchers(
    db: Session,
    *,
    package: MonthlyWorkPackage,
    existing_source_keys: set[str],
    account_names: dict[str, str],
) -> list[Voucher]:
    created: list[Voucher] = []
    matched_transaction_ids = _valid_matched_transaction_ids(db, package=package)
    transactions = db.scalars(
        select(BankTransaction)
        .where(
            BankTransaction.organization_id == package.organization_id,
            BankTransaction.monthly_work_package_id == package.id,
        )
        .order_by(BankTransaction.transaction_date, BankTransaction.id)
    ).all()

    for transaction in transactions:
        if transaction.id in matched_transaction_ids:
            continue
        source_key = f"bank:{transaction.id}"
        if source_key in existing_source_keys:
            continue

        amount = _transaction_amount(transaction)
        if amount == Decimal("0.00"):
            continue
        summary, lines, ai_reason = _single_bank_voucher_recommendation(transaction, amount=amount)

        voucher = _build_voucher(
            package=package,
            voucher_date=transaction.transaction_date,
            summary=summary,
            source_type="BANK_TRANSACTION",
            source_id=str(transaction.id),
            source_key=source_key,
            source_data=_source_data_for_bank_transaction(transaction),
            ai_confidence=45,
            ai_reason=ai_reason,
            account_names=account_names,
            lines=lines,
        )
        db.add(voucher)
        db.flush()
        existing_source_keys.add(source_key)
        created.append(voucher)

    return created


def _refresh_existing_pending_single_bank_vouchers(
    db: Session,
    *,
    package: MonthlyWorkPackage,
    account_names: dict[str, str],
) -> None:
    vouchers = db.scalars(
        select(Voucher)
        .options(selectinload(Voucher.entries))
        .where(
            Voucher.organization_id == package.organization_id,
            Voucher.monthly_work_package_id == package.id,
            Voucher.status == "PENDING_CONFIRMATION",
            Voucher.source_key.like("bank:%"),
        )
    ).all()
    for voucher in vouchers:
        source_data = dict(voucher.source_data or {})
        if _source_uuid(source_data.get("invoice_id")) is not None:
            continue
        bank_transaction_id = _source_uuid(source_data.get("bank_transaction_id"))
        if bank_transaction_id is None:
            continue
        transaction = _get_package_source(db, BankTransaction, bank_transaction_id, package.organization_id, package.id)
        if transaction is None or "手续费" in (transaction.summary or ""):
            continue

        amount = _transaction_amount(transaction)
        if amount == Decimal("0.00"):
            continue
        summary, lines, ai_reason = _single_bank_voucher_recommendation(transaction, amount=amount)
        voucher.summary = summary
        voucher.ai_reason = ai_reason
        voucher.source_data = _source_data_for_bank_transaction(transaction)
        voucher.entries = [
            VoucherEntry(
                channel_id=DEFAULT_CHANNEL_ID,
                organization_id=package.organization_id,
                line_no=index,
                direction=direction,
                account_code=account_code,
                account_name=account_names.get(account_code, ""),
                amount=_money(line_amount),
                source_type="BANK_TRANSACTION",
                source_id=str(transaction.id),
            )
            for index, (direction, account_code, line_amount) in enumerate(lines, start=1)
        ]
        voucher.validation_errors = validate_voucher(db, voucher)


def _single_bank_voucher_recommendation(
    transaction: BankTransaction,
    *,
    amount: Decimal,
) -> tuple[str, list[tuple[str, str, Decimal]], str]:
    if transaction.debit_amount and _money(transaction.debit_amount) != Decimal("0.00"):
        return (
            "记录银行付款待补发票",
            [
                ("DEBIT", "1123", amount),
                ("CREDIT", "1002", amount),
            ],
            "银行付款暂无匹配发票，先按预付账款暂挂，需人工确认业务归属或重新匹配发票",
        )
    return (
        "记录银行收款待补发票",
        [
            ("DEBIT", "1002", amount),
            ("CREDIT", "2203", amount),
        ],
        "银行收款暂无匹配发票，先按预收账款暂挂，需人工确认业务归属或重新匹配发票",
    )


def _valid_matched_transaction_ids(db: Session, *, package: MonthlyWorkPackage) -> set[UUID]:
    return set(
        db.scalars(
            select(MatchRecord.bank_transaction_id)
            .join(BankTransaction, BankTransaction.id == MatchRecord.bank_transaction_id)
            .outerjoin(Invoice, Invoice.id == MatchRecord.invoice_id)
            .where(
                MatchRecord.organization_id == package.organization_id,
                MatchRecord.monthly_work_package_id == package.id,
                MatchRecord.bank_transaction_id.is_not(None),
                MatchRecord.confirmation_status.in_(("AUTO_CONFIRMED", "CONFIRMED")),
                BankTransaction.organization_id == package.organization_id,
                BankTransaction.monthly_work_package_id == package.id,
                or_(
                    MatchRecord.invoice_id.is_(None),
                    (
                        (Invoice.organization_id == package.organization_id)
                        & (Invoice.monthly_work_package_id == package.id)
                    ),
                ),
            )
        )
    )


def _valid_matched_invoice_ids(db: Session, *, package: MonthlyWorkPackage) -> set[UUID]:
    return set(
        db.scalars(
            select(MatchRecord.invoice_id)
            .join(Invoice, Invoice.id == MatchRecord.invoice_id)
            .outerjoin(BankTransaction, BankTransaction.id == MatchRecord.bank_transaction_id)
            .where(
                MatchRecord.organization_id == package.organization_id,
                MatchRecord.monthly_work_package_id == package.id,
                MatchRecord.invoice_id.is_not(None),
                MatchRecord.confirmation_status.in_(("AUTO_CONFIRMED", "CONFIRMED")),
                Invoice.organization_id == package.organization_id,
                Invoice.monthly_work_package_id == package.id,
                or_(
                    MatchRecord.bank_transaction_id.is_(None),
                    (
                        (BankTransaction.organization_id == package.organization_id)
                        & (BankTransaction.monthly_work_package_id == package.id)
                    ),
                ),
            )
        )
    )


def _build_voucher(
    *,
    package: MonthlyWorkPackage,
    voucher_date: date,
    summary: str,
    source_type: str,
    source_id: str,
    source_key: str,
    source_data: dict,
    ai_confidence: int,
    ai_reason: str,
    account_names: dict[str, str],
    lines: list[tuple[str, str, Decimal]],
) -> Voucher:
    voucher = Voucher(
        channel_id=DEFAULT_CHANNEL_ID,
        organization_id=package.organization_id,
        monthly_work_package_id=package.id,
        voucher_date=voucher_date,
        summary=summary,
        source_key=source_key,
        source_data=source_data,
        status="PENDING_CONFIRMATION",
        ai_confidence=ai_confidence,
        ai_reason=ai_reason,
    )
    voucher.entries = [
        VoucherEntry(
            channel_id=DEFAULT_CHANNEL_ID,
            organization_id=package.organization_id,
            line_no=index,
            direction=direction,
            account_code=account_code,
            account_name=account_names.get(account_code, ""),
            amount=_money(amount),
            source_type=source_type,
            source_id=source_id,
        )
        for index, (direction, account_code, amount) in enumerate(lines, start=1)
    ]
    return voucher


def _output_invoice_lines(invoice: Invoice) -> list[tuple[str, str, Decimal]]:
    lines = [
        ("DEBIT", "1002", invoice.total_amount),
        ("CREDIT", "5001", invoice.amount),
    ]
    if _money(invoice.tax_amount) != Decimal("0.00"):
        lines.append(("CREDIT", "22210102", invoice.tax_amount))
    return lines


def _output_invoice_accrual_lines(invoice: Invoice) -> list[tuple[str, str, Decimal]]:
    lines = [
        ("DEBIT", "1122", invoice.total_amount),
        ("CREDIT", "5001", invoice.amount),
    ]
    if _money(invoice.tax_amount) != Decimal("0.00"):
        lines.append(("CREDIT", "22210102", invoice.tax_amount))
    return lines


def _input_invoice_lines(invoice: Invoice) -> list[tuple[str, str, Decimal]]:
    lines = [
        ("DEBIT", "560203", invoice.amount),
    ]
    if _money(invoice.tax_amount) != Decimal("0.00"):
        lines.append(("DEBIT", "22210101", invoice.tax_amount))
    lines.append(("CREDIT", "1002", invoice.total_amount))
    return lines


def _input_invoice_accrual_lines(invoice: Invoice) -> list[tuple[str, str, Decimal]]:
    lines = [
        ("DEBIT", "560203", invoice.amount),
    ]
    if _money(invoice.tax_amount) != Decimal("0.00"):
        lines.append(("DEBIT", "22210101", invoice.tax_amount))
    lines.append(("CREDIT", "2202", invoice.total_amount))
    return lines


def _combined_output_invoice_lines(transaction: BankTransaction, invoices: list[Invoice]) -> list[tuple[str, str, Decimal]]:
    revenue_total = sum((_money(invoice.amount) for invoice in invoices), Decimal("0.00"))
    tax_total = sum((_money(invoice.tax_amount) for invoice in invoices), Decimal("0.00"))
    invoice_total = revenue_total + tax_total
    bank_amount = _transaction_amount(transaction)
    difference = _money(invoice_total - bank_amount)
    lines = [
        ("DEBIT", "1002", bank_amount),
        ("CREDIT", "5001", revenue_total),
    ]
    if tax_total != Decimal("0.00"):
        lines.append(("CREDIT", "22210102", tax_total))
    if difference > Decimal("0.00"):
        lines.append(("DEBIT", "1122", difference))
    if difference < Decimal("0.00"):
        lines.append(("CREDIT", "2203", abs(difference)))
    return [(direction, account_code, amount) for direction, account_code, amount in lines if _money(amount) != Decimal("0.00")]


def _combined_input_invoice_lines(transaction: BankTransaction, invoices: list[Invoice]) -> list[tuple[str, str, Decimal]]:
    expense_total = sum((_money(invoice.amount) for invoice in invoices), Decimal("0.00"))
    tax_total = sum((_money(invoice.tax_amount) for invoice in invoices), Decimal("0.00"))
    invoice_total = expense_total + tax_total
    bank_amount = _transaction_amount(transaction)
    difference = _money(invoice_total - bank_amount)
    lines = [
        ("DEBIT", "560203", expense_total),
    ]
    if tax_total != Decimal("0.00"):
        lines.append(("DEBIT", "22210101", tax_total))
    if difference < Decimal("0.00"):
        lines.append(("DEBIT", "1123", abs(difference)))
    lines.append(("CREDIT", "1002", bank_amount))
    if difference > Decimal("0.00"):
        lines.append(("CREDIT", "2202", difference))
    return [(direction, account_code, amount) for direction, account_code, amount in lines if _money(amount) != Decimal("0.00")]


def _output_invoice_difference_lines(transaction: BankTransaction, invoice: Invoice) -> list[tuple[str, str, Decimal]]:
    bank_amount = _transaction_amount(transaction)
    invoice_total = _money(invoice.total_amount)
    difference = _money(invoice_total - bank_amount)
    lines = [
        ("DEBIT", "1002", bank_amount),
    ]
    if difference > Decimal("0.00"):
        lines.append(("DEBIT", "1122", difference))
    lines.append(("CREDIT", "5001", invoice.amount))
    if _money(invoice.tax_amount) != Decimal("0.00"):
        lines.append(("CREDIT", "22210102", invoice.tax_amount))
    if difference < Decimal("0.00"):
        lines.append(("CREDIT", "2203", abs(difference)))
    return [(direction, account_code, amount) for direction, account_code, amount in lines if _money(amount) != Decimal("0.00")]


def _input_invoice_difference_lines(transaction: BankTransaction, invoice: Invoice) -> list[tuple[str, str, Decimal]]:
    bank_amount = _transaction_amount(transaction)
    invoice_total = _money(invoice.total_amount)
    difference = _money(invoice_total - bank_amount)
    lines = [
        ("DEBIT", "560203", invoice.amount),
    ]
    if _money(invoice.tax_amount) != Decimal("0.00"):
        lines.append(("DEBIT", "22210101", invoice.tax_amount))
    if difference < Decimal("0.00"):
        lines.append(("DEBIT", "1123", abs(difference)))
    lines.append(("CREDIT", "1002", bank_amount))
    if difference > Decimal("0.00"):
        lines.append(("CREDIT", "2202", difference))
    return [(direction, account_code, amount) for direction, account_code, amount in lines if _money(amount) != Decimal("0.00")]


def _transaction_amount(transaction: BankTransaction) -> Decimal:
    debit_amount = _money(transaction.debit_amount or Decimal("0.00"))
    credit_amount = _money(transaction.credit_amount or Decimal("0.00"))
    if debit_amount != Decimal("0.00"):
        return debit_amount
    return credit_amount


def _single_source_voucher_amount(
    db: Session,
    *,
    package: MonthlyWorkPackage,
    bank_transaction_id: UUID | None,
    invoice_id: UUID | None,
) -> Decimal:
    if bank_transaction_id is not None:
        transaction = _get_package_source(db, BankTransaction, bank_transaction_id, package.organization_id, package.id)
        if transaction is None:
            raise VoucherDomainError("Bank transaction not found in current package.")
        return _transaction_amount(transaction)
    if invoice_id is not None:
        invoice = _get_package_source(db, Invoice, invoice_id, package.organization_id, package.id)
        if invoice is None:
            raise VoucherDomainError("Invoice not found in current package.")
        return _money(invoice.total_amount)
    return Decimal("0.00")


def _source_data_for_match(
    match: MatchRecord,
    transaction: BankTransaction,
    invoice: Invoice,
    *,
    force_task_type: str | None = None,
) -> dict:
    task_type = force_task_type or "FULL_MATCH"
    difference_amount = _money(invoice.total_amount) - _transaction_amount(transaction)
    return {
        "source_group_type": task_type,
        "voucher_task_type": task_type,
        "difference_amount": _money_text(difference_amount),
        "match_record_id": str(match.id),
        "bank_transaction_id": str(transaction.id),
        "invoice_id": str(invoice.id),
        "match": _match_source_data(match),
        "bank_transaction": _bank_transaction_source_data(transaction),
        "invoice": _invoice_source_data(invoice),
    }


def _source_data_for_one_invoice_multiple_bank_group(
    group: list[tuple[MatchRecord, BankTransaction, Invoice]],
    source_key: str,
) -> dict:
    invoice = group[0][2]
    matches = [match for match, _, _ in group]
    transactions = sorted((transaction for _, transaction, _ in group), key=lambda item: (item.transaction_date, item.id))
    return {
        "source_group_id": source_key,
        "source_group_type": "ONE_INVOICE_MULTIPLE_BANK_TRANSACTIONS",
        "voucher_task_type": "FULL_MATCH",
        "difference_amount": "0.00",
        "invoice_id": str(invoice.id),
        "invoice_ids": [str(invoice.id)],
        "bank_transaction_ids": [str(transaction.id) for transaction in transactions],
        "match_record_ids": [str(match.id) for match in matches],
        "invoice": _invoice_source_data(invoice),
        "bank_transactions": [_bank_transaction_source_data(transaction) for transaction in transactions],
        "matches": [_match_source_data(match) for match in matches],
    }


def _source_data_for_one_bank_multiple_invoice_group(
    group: list[tuple[MatchRecord, BankTransaction, Invoice]],
    source_key: str,
) -> dict:
    transaction = group[0][1]
    matches = [match for match, _, _ in group]
    invoices = sorted((invoice for _, _, invoice in group), key=lambda item: (item.invoice_date, item.id))
    invoice_total = sum((_money(invoice.total_amount) for invoice in invoices), Decimal("0.00"))
    difference_amount = _money(invoice_total - _transaction_amount(transaction))
    return {
        "source_group_id": source_key,
        "source_group_type": "ONE_BANK_TRANSACTION_MULTIPLE_INVOICES",
        "voucher_task_type": "DIFFERENCE_COMPLETION" if difference_amount != Decimal("0.00") else "FULL_MATCH",
        "difference_amount": _money_text(difference_amount),
        "bank_transaction_id": str(transaction.id),
        "bank_transaction_ids": [str(transaction.id)],
        "invoice_ids": [str(invoice.id) for invoice in invoices],
        "match_record_ids": [str(match.id) for match in matches],
        "bank_transaction": _bank_transaction_source_data(transaction),
        "invoices": [_invoice_source_data(invoice) for invoice in invoices],
        "matches": [_match_source_data(match) for match in matches],
    }


def _source_data_for_bank_transaction(transaction: BankTransaction) -> dict:
    return {
        "source_group_type": "BANK_ONLY",
        "voucher_task_type": "SINGLE_SOURCE",
        "difference_amount": "0.00",
        "bank_transaction_id": str(transaction.id),
        "bank_transaction": _bank_transaction_source_data(transaction),
    }


def _source_data_for_invoice(invoice: Invoice) -> dict:
    return {
        "source_group_type": "INVOICE_ONLY",
        "voucher_task_type": "SINGLE_SOURCE",
        "difference_amount": "0.00",
        "invoice_id": str(invoice.id),
        "invoice": _invoice_source_data(invoice),
    }


def _get_voucher_for_operation(db: Session, *, voucher_id: UUID) -> Voucher:
    organization_id = get_current_organization_id()
    voucher = db.scalar(
        select(Voucher)
        .options(selectinload(Voucher.entries))
        .where(
            Voucher.id == voucher_id,
            Voucher.organization_id == organization_id,
        )
    )
    if voucher is None:
        raise VoucherDomainError("Voucher not found in current organization.")
    return voucher


def _get_package_for_operation(db: Session, *, monthly_work_package_id: UUID) -> MonthlyWorkPackage:
    organization_id = get_current_organization_id()
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None or package.organization_id != organization_id:
        raise VoucherDomainError("Monthly work package not found in current organization.")
    return package


def _voucher_source_link_index(db: Session, *, package: MonthlyWorkPackage) -> dict[str, dict[UUID, list[Voucher]]]:
    bank_index: dict[UUID, list[Voucher]] = {}
    invoice_index: dict[UUID, list[Voucher]] = {}
    vouchers = db.scalars(
        select(Voucher).where(
            Voucher.organization_id == package.organization_id,
            Voucher.monthly_work_package_id == package.id,
            Voucher.status != "REJECTED",
        )
    ).all()
    for voucher in vouchers:
        source_data = voucher.source_data or {}
        bank_ids = _source_uuid_list(source_data.get("bank_transaction_ids")) or _source_uuid_list(
            source_data.get("bank_transaction_id")
        )
        invoice_ids = _source_uuid_list(source_data.get("invoice_ids")) or _source_uuid_list(source_data.get("invoice_id"))
        for bank_id in bank_ids:
            bank_index.setdefault(bank_id, []).append(voucher)
        for invoice_id in invoice_ids:
            invoice_index.setdefault(invoice_id, []).append(voucher)
    return {"bank": bank_index, "invoice": invoice_index}


def _match_source_link_index(db: Session, *, package: MonthlyWorkPackage) -> dict[str, dict[UUID, list[MatchRecord]]]:
    bank_index: dict[UUID, list[MatchRecord]] = {}
    invoice_index: dict[UUID, list[MatchRecord]] = {}
    matches = db.scalars(
        select(MatchRecord).where(
            MatchRecord.organization_id == package.organization_id,
            MatchRecord.monthly_work_package_id == package.id,
            MatchRecord.confirmation_status.in_(("AUTO_CONFIRMED", "CONFIRMED")),
        )
    ).all()
    for match in matches:
        if match.bank_transaction_id:
            bank_index.setdefault(match.bank_transaction_id, []).append(match)
        if match.invoice_id:
            invoice_index.setdefault(match.invoice_id, []).append(match)
    return {"bank": bank_index, "invoice": invoice_index}


def _ledger_voucher_status(vouchers: list[Voucher]) -> str:
    if not vouchers:
        return "UNPROCESSED"
    statuses = {voucher.status for voucher in vouchers}
    if "PENDING_CONFIRMATION" in statuses:
        return "PENDING_CONFIRMATION"
    if "CONFIRMED" in statuses:
        return "CONFIRMED"
    return sorted(statuses)[0]


def _ledger_voucher_status_label(status_value: str) -> str:
    labels = {
        "UNPROCESSED": "未处理",
        "PENDING_CONFIRMATION": "待确认",
        "CONFIRMED": "已确认",
        "REJECTED": "已驳回",
    }
    return labels.get(status_value or "", status_value or "未处理")


def _matching_status_label(status_value: str) -> str:
    labels = {
        "MATCHED": "已匹配",
        "UNMATCHED": "未匹配",
    }
    return labels.get(status_value or "", status_value or "未匹配")


def _linked_voucher_numbers(vouchers: list[Voucher]) -> list[str]:
    return [voucher.voucher_number or "未编号" for voucher in vouchers]


def _linked_voucher_reads(vouchers: list[Voucher]) -> list[dict]:
    return [
        {
            "id": voucher.id,
            "voucher_number": voucher.voucher_number or "未编号",
            "status": voucher.status,
            "status_label": _ledger_voucher_status_label(voucher.status),
            "summary": voucher.summary,
            "task_type": str((voucher.source_data or {}).get("voucher_task_type") or "UNKNOWN"),
            "ai_confidence": voucher.ai_confidence,
        }
        for voucher in vouchers
    ]


def _bank_transaction_direction(transaction: BankTransaction) -> str:
    debit_amount = _money(transaction.debit_amount or Decimal("0.00"))
    credit_amount = _money(transaction.credit_amount or Decimal("0.00"))
    if debit_amount != Decimal("0.00") and credit_amount == Decimal("0.00"):
        return "OUTFLOW"
    if credit_amount != Decimal("0.00") and debit_amount == Decimal("0.00"):
        return "INFLOW"
    return "UNKNOWN"


def _voucher_gross_amount(voucher: Voucher) -> Decimal:
    debit_total = sum(
        (_money(entry.amount) for entry in voucher.entries if entry.direction == "DEBIT"),
        Decimal("0.00"),
    )
    credit_total = sum(
        (_money(entry.amount) for entry in voucher.entries if entry.direction == "CREDIT"),
        Decimal("0.00"),
    )
    return max(debit_total, credit_total)


def _record_voucher_rule_from_user_edit(
    db: Session,
    *,
    package: MonthlyWorkPackage,
    voucher: Voucher,
    treatment: dict,
    bank_transaction_id: UUID | None,
    invoice_id: UUID | None,
) -> None:
    counterparty = ""
    source_direction = None
    invoice_direction = None
    summary_keywords: list[str] = []
    if bank_transaction_id is not None:
        transaction = _get_package_source(db, BankTransaction, bank_transaction_id, package.organization_id, package.id)
        if transaction is not None:
            counterparty = (transaction.counterparty_name or "").strip()
            source_direction = _bank_transaction_direction(transaction)
            if transaction.summary:
                summary_keywords.append(transaction.summary.strip()[:40])
    if invoice_id is not None:
        invoice = _get_package_source(db, Invoice, invoice_id, package.organization_id, package.id)
        if invoice is not None:
            counterparty = counterparty or _invoice_counterparty(invoice).strip()
            invoice_direction = invoice.invoice_direction
            if invoice.invoice_number:
                summary_keywords.append(invoice.invoice_number.strip()[:40])
    treatment_type = (treatment.get("treatment_type") or "人工调整").strip()
    rule_counterparty = counterparty or "未识别对方"
    rule_name = f"{treatment_type}-{rule_counterparty}"[:120]

    existing_rule = db.scalar(
        select(VoucherRule).where(
            VoucherRule.organization_id == package.organization_id,
            VoucherRule.enterprise_id == package.enterprise_id,
            VoucherRule.rule_name == rule_name,
        )
    )
    rule_payload = {
        "summary_keywords": summary_keywords,
        "counterparty_pattern": counterparty or None,
        "source_direction": source_direction,
        "invoice_direction": invoice_direction,
        "summary_template": treatment.get("summary") or voucher.summary,
        "debit_account_code": treatment["debit_account_code"],
        "credit_account_code": treatment["credit_account_code"],
        "tax_account_code": None,
        "require_confirmation": True,
    }
    if existing_rule is None:
        db.add(
            VoucherRule(
                channel_id=DEFAULT_CHANNEL_ID,
                organization_id=package.organization_id,
                enterprise_id=package.enterprise_id,
                rule_name=rule_name,
                **rule_payload,
            )
        )
        return
    for key, value in rule_payload.items():
        setattr(existing_rule, key, value)


def _used_non_rejected_voucher_source_ids(db: Session, *, package_id: UUID, exclude_voucher_id: UUID) -> dict[str, dict[UUID, str]]:
    used_bank_ids: dict[UUID, str] = {}
    used_invoice_ids: dict[UUID, str] = {}
    vouchers = db.scalars(
        select(Voucher).where(
            Voucher.monthly_work_package_id == package_id,
            Voucher.id != exclude_voucher_id,
            Voucher.status != "REJECTED",
        )
    ).all()
    for voucher in vouchers:
        source_data = voucher.source_data or {}
        bank_ids = _source_uuid_list(source_data.get("bank_transaction_ids")) or _source_uuid_list(
            source_data.get("bank_transaction_id")
        )
        invoice_ids = _source_uuid_list(source_data.get("invoice_ids")) or _source_uuid_list(source_data.get("invoice_id"))
        is_pair_voucher = bool(bank_ids and invoice_ids)
        is_confirmed = voucher.status == "CONFIRMED"
        if not is_pair_voucher and not is_confirmed:
            continue
        for bank_id in bank_ids:
            used_bank_ids[bank_id] = _preferred_used_status(used_bank_ids.get(bank_id), voucher.status)
        for invoice_id in invoice_ids:
            used_invoice_ids[invoice_id] = _preferred_used_status(used_invoice_ids.get(invoice_id), voucher.status)
    return {"bank_transaction_ids": used_bank_ids, "invoice_ids": used_invoice_ids}


def _preferred_used_status(current: str | None, next_status: str) -> str:
    priority = {"CONFIRMED": 3, "PENDING_CONFIRMATION": 2, "DRAFT": 1}
    if current is None:
        return next_status
    return next_status if priority.get(next_status, 0) > priority.get(current, 0) else current


def _retire_single_source_vouchers(
    db: Session,
    *,
    package_id: UUID,
    exclude_voucher_id: UUID,
    bank_transaction_ids: list[UUID],
    invoice_ids: list[UUID],
) -> None:
    bank_id_set = set(bank_transaction_ids)
    invoice_id_set = set(invoice_ids)
    vouchers = db.scalars(
        select(Voucher).where(
            Voucher.monthly_work_package_id == package_id,
            Voucher.id != exclude_voucher_id,
            Voucher.status == "PENDING_CONFIRMATION",
        )
    ).all()
    for voucher in vouchers:
        source_data = voucher.source_data or {}
        voucher_bank_id = _source_uuid(source_data.get("bank_transaction_id"))
        voucher_invoice_id = _source_uuid(source_data.get("invoice_id"))
        is_single_bank = voucher_bank_id is not None and voucher_invoice_id is None
        is_single_invoice = voucher_invoice_id is not None and voucher_bank_id is None
        should_retire = (is_single_bank and voucher_bank_id in bank_id_set) or (
            is_single_invoice and voucher_invoice_id in invoice_id_set
        )
        if not should_retire:
            continue
        voucher.status = "REJECTED"
        errors = list(voucher.validation_errors or [])
        _append_once(errors, "SOURCE_REASSIGNED")
        voucher.validation_errors = errors


def _invoice_rematch_candidate(
    invoice: Invoice,
    transaction: BankTransaction,
    *,
    is_current: bool = False,
    used_by_status: str | None = None,
) -> dict:
    amount_score = 70 if _money(invoice.total_amount) == _transaction_amount(transaction) else 0
    date_score = _date_proximity_score(transaction.transaction_date, invoice.invoice_date)
    name_score = _counterparty_overlap_score(transaction.counterparty_name, _invoice_counterparty(invoice))
    score = amount_score + date_score + name_score
    reason_parts = []
    if amount_score:
        reason_parts.append("金额一致")
    if date_score:
        reason_parts.append("日期接近")
    if name_score:
        reason_parts.append("对方名称相近")
    return {
        "id": invoice.id,
        "source_type": "INVOICE",
        "date": invoice.invoice_date,
        "amount": _money(invoice.total_amount),
        "counterparty": _invoice_counterparty(invoice),
        "counterparty_role": _invoice_counterparty_role(invoice),
        "direction_label": _invoice_direction_label(invoice.invoice_direction),
        "description": f"{_invoice_direction_label(invoice.invoice_direction)} {invoice.invoice_number or ''}".strip(),
        "score": min(score, 100),
        "reason": "、".join(reason_parts) if reason_parts else "待人工判断",
        "detail": _invoice_candidate_detail(invoice),
        **_rematch_candidate_usage_flags(is_current=is_current, used_by_status=used_by_status),
    }


def _bank_rematch_candidate(
    transaction: BankTransaction,
    invoice: Invoice,
    *,
    is_current: bool = False,
    used_by_status: str | None = None,
) -> dict:
    amount_score = 70 if _transaction_amount(transaction) == _money(invoice.total_amount) else 0
    date_score = _date_proximity_score(transaction.transaction_date, invoice.invoice_date)
    name_score = _counterparty_overlap_score(transaction.counterparty_name, _invoice_counterparty(invoice))
    score = amount_score + date_score + name_score
    reason_parts = []
    if amount_score:
        reason_parts.append("金额一致")
    if date_score:
        reason_parts.append("日期接近")
    if name_score:
        reason_parts.append("对方名称相近")
    return {
        "id": transaction.id,
        "source_type": "BANK_TRANSACTION",
        "date": transaction.transaction_date,
        "amount": _transaction_amount(transaction),
        "counterparty": transaction.counterparty_name or "",
        "counterparty_role": "交易对方",
        "direction_label": _bank_transaction_direction_label(transaction),
        "description": transaction.summary or "",
        "score": min(score, 100),
        "reason": "、".join(reason_parts) if reason_parts else "待人工判断",
        "detail": _bank_candidate_detail(transaction),
        **_rematch_candidate_usage_flags(is_current=is_current, used_by_status=used_by_status),
    }


def _rematch_candidate_usage_flags(*, is_current: bool, used_by_status: str | None) -> dict:
    if is_current:
        return {
            "is_current": True,
            "is_used": False,
            "is_selectable": False,
            "used_by_status": None,
            "disabled_reason": "当前凭证正在使用",
        }
    if used_by_status:
        return {
            "is_current": False,
            "is_used": True,
            "is_selectable": False,
            "used_by_status": used_by_status,
            "disabled_reason": f"已被{_voucher_status_reason_label(used_by_status)}凭证使用",
        }
    return {
        "is_current": False,
        "is_used": False,
        "is_selectable": True,
        "used_by_status": None,
        "disabled_reason": "",
    }


def _voucher_status_reason_label(status_value: str) -> str:
    labels = {
        "CONFIRMED": "已确认",
        "PENDING_CONFIRMATION": "待确认",
        "DRAFT": "草稿",
    }
    return labels.get(status_value, status_value or "其他")


def _date_proximity_score(left: date | None, right: date | None) -> int:
    if left is None or right is None:
        return 0
    distance = abs((left - right).days)
    if distance <= 3:
        return 20
    if distance <= 7:
        return 14
    if distance <= 15:
        return 6
    return 0


def _counterparty_overlap_score(left: str | None, right: str | None) -> int:
    left_text = (left or "").strip()
    right_text = (right or "").strip()
    if not left_text or not right_text:
        return 0
    if left_text in right_text or right_text in left_text:
        return 10
    left_tokens = set(left_text.replace("（", "").replace("）", "").replace("(", "").replace(")", ""))
    right_tokens = set(right_text.replace("（", "").replace("）", "").replace("(", "").replace(")", ""))
    return 6 if len(left_tokens & right_tokens) >= 4 else 0


def _invoice_counterparty(invoice: Invoice) -> str:
    if invoice.invoice_direction == "INPUT":
        return invoice.seller_name or _raw_invoice_value(invoice, ("销方名称", "销售方名称", "销售方"))
    if invoice.invoice_direction == "OUTPUT":
        return invoice.buyer_name or _raw_invoice_value(invoice, ("购买方名称", "购方名称", "购买方"))
    return invoice.seller_name or invoice.buyer_name or _raw_invoice_value(invoice, ("销方名称", "销售方名称", "购买方名称", "购方名称"))


def _invoice_counterparty_role(invoice: Invoice) -> str:
    if invoice.invoice_direction == "INPUT":
        return "销售方"
    if invoice.invoice_direction == "OUTPUT":
        return "购买方"
    return "对方"


def _invoice_direction_label(direction: str | None) -> str:
    labels = {"INPUT": "进项发票", "OUTPUT": "销项发票"}
    return labels.get(direction or "", direction or "")


def _bank_transaction_direction_label(transaction: BankTransaction) -> str:
    debit_amount = _money(transaction.debit_amount or Decimal("0.00"))
    credit_amount = _money(transaction.credit_amount or Decimal("0.00"))
    if debit_amount != Decimal("0.00") and credit_amount == Decimal("0.00"):
        return "付款/转出"
    if credit_amount != Decimal("0.00") and debit_amount == Decimal("0.00"):
        return "收款/转入"
    return "收付待判断"


def _invoice_candidate_detail(invoice: Invoice) -> dict:
    return {
        "invoice_direction": _invoice_direction_label(invoice.invoice_direction),
        "invoice_number": invoice.invoice_number or "",
        "invoice_date": _date_text(invoice.invoice_date),
        "seller_name": invoice.seller_name or _raw_invoice_value(invoice, ("销方名称", "销售方名称", "销售方")),
        "buyer_name": invoice.buyer_name or _raw_invoice_value(invoice, ("购买方名称", "购方名称", "购买方")),
        "counterparty_role": _invoice_counterparty_role(invoice),
        "counterparty_name": _invoice_counterparty(invoice),
        "amount": _money_text(invoice.amount),
        "tax_amount": _money_text(invoice.tax_amount),
        "total_amount": _money_text(invoice.total_amount),
        "status": invoice.status,
    }


def _bank_candidate_detail(transaction: BankTransaction) -> dict:
    return {
        "direction_label": _bank_transaction_direction_label(transaction),
        "transaction_date": _date_text(transaction.transaction_date),
        "summary": transaction.summary or "",
        "counterparty_name": transaction.counterparty_name or "",
        "counterparty_account": transaction.counterparty_account or "",
        "debit_amount": _money_text(transaction.debit_amount),
        "credit_amount": _money_text(transaction.credit_amount),
        "balance": _money_text(transaction.balance) if transaction.balance is not None else "",
    }


def _raw_invoice_value(invoice: Invoice, keys: tuple[str, ...]) -> str:
    raw_row = invoice.raw_row_data or {}
    for key in keys:
        value = raw_row.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return ""


def _enrich_voucher_source_data(db: Session, voucher: Voucher | None) -> Voucher | None:
    if voucher is None:
        return None
    source_data = dict(voucher.source_data or {})
    organization_id = voucher.organization_id
    package_id = voucher.monthly_work_package_id

    transaction_id = _source_uuid(source_data.get("bank_transaction_id"))
    if transaction_id and "bank_transaction" not in source_data:
        transaction = _get_package_source(db, BankTransaction, transaction_id, organization_id, package_id)
        if transaction is not None:
            source_data["bank_transaction"] = _bank_transaction_source_data(transaction)

    invoice_id = _source_uuid(source_data.get("invoice_id"))
    if invoice_id and "invoice" not in source_data:
        invoice = _get_package_source(db, Invoice, invoice_id, organization_id, package_id)
        if invoice is not None:
            source_data["invoice"] = _invoice_source_data(invoice)

    match_id = _source_uuid(source_data.get("match_record_id"))
    if match_id and "match" not in source_data:
        match = _get_package_source(db, MatchRecord, match_id, organization_id, package_id)
        if match is not None:
            source_data["match"] = _match_source_data(match)

    voucher.source_data = source_data
    return voucher


def _get_package_source(db: Session, model, source_id: UUID, organization_id: UUID, package_id: UUID):
    return db.scalar(
        select(model).where(
            model.id == source_id,
            model.organization_id == organization_id,
            model.monthly_work_package_id == package_id,
        )
    )


def _bank_transaction_source_data(transaction: BankTransaction) -> dict:
    return {
        "id": str(transaction.id),
        "direction_label": _bank_transaction_direction_label(transaction),
        "transaction_date": _date_text(transaction.transaction_date),
        "summary": transaction.summary,
        "debit_amount": _money_text(transaction.debit_amount),
        "credit_amount": _money_text(transaction.credit_amount),
        "counterparty_name": transaction.counterparty_name or "",
        "counterparty_account": transaction.counterparty_account or "",
        "balance": _money_text(transaction.balance) if transaction.balance is not None else "",
        "raw_row_data": transaction.raw_row_data or {},
    }


def _invoice_source_data(invoice: Invoice) -> dict:
    return {
        "id": str(invoice.id),
        "invoice_direction": invoice.invoice_direction,
        "invoice_direction_label": _invoice_direction_label(invoice.invoice_direction),
        "counterparty_role": _invoice_counterparty_role(invoice),
        "counterparty_name": _invoice_counterparty(invoice),
        "invoice_number": invoice.invoice_number,
        "invoice_date": _date_text(invoice.invoice_date),
        "amount": _money_text(invoice.amount),
        "tax_amount": _money_text(invoice.tax_amount),
        "total_amount": _money_text(invoice.total_amount),
        "seller_name": invoice.seller_name or "",
        "buyer_name": invoice.buyer_name or "",
        "status": invoice.status,
        "raw_row_data": invoice.raw_row_data or {},
    }


def _match_source_data(match: MatchRecord) -> dict:
    return {
        "id": str(match.id),
        "match_method": match.match_method,
        "confidence": match.confidence,
        "explanation": match.explanation,
        "confirmation_status": match.confirmation_status,
    }


def _composite_source_key(kind: str, *, bank_transaction_ids: list[UUID], invoice_ids: list[UUID]) -> str:
    raw_parts = [
        kind,
        *[f"bank:{source_id}" for source_id in sorted(bank_transaction_ids)],
        *[f"invoice:{source_id}" for source_id in sorted(invoice_ids)],
    ]
    digest = hashlib.sha1("|".join(raw_parts).encode("utf-8")).hexdigest()[:24]
    return f"group:{digest}"


def _source_uuid(value) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _source_uuid_list(value) -> list[UUID]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    source_ids: list[UUID] = []
    for item in values:
        source_id = _source_uuid(item)
        if source_id is not None and source_id not in source_ids:
            source_ids.append(source_id)
    return source_ids


def _rematch_source_ids(
    *,
    explicit_ids: list[UUID] | None,
    explicit_id: UUID | None,
    source_ids,
    source_id,
) -> list[UUID]:
    if explicit_ids:
        return _source_uuid_list(explicit_ids)
    if explicit_id:
        return _source_uuid_list(explicit_id)
    return _source_uuid_list(source_ids) or _source_uuid_list(source_id)


def _date_text(value: date) -> str:
    return value.isoformat() if value else ""


def _money_text(value: Decimal) -> str:
    return str(_money(value or Decimal("0.00")))


def _next_voucher_number(db: Session, *, monthly_work_package_id: UUID) -> str:
    confirmed_count = db.scalar(
        select(func.count())
        .select_from(Voucher)
        .where(
            Voucher.monthly_work_package_id == monthly_work_package_id,
            Voucher.status == "CONFIRMED",
        )
    )
    return f"记-{int(confirmed_count or 0) + 1:04d}"


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def _date_in_period(value: date, *, year: int, month: int) -> bool:
    last_day = monthrange(year, month)[1]
    return date(year, month, 1) <= value <= date(year, month, last_day)


def _append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
