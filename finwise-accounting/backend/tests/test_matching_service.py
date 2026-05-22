from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from app.models import AccountingLine, BankTransaction, Enterprise, Invoice, MatchRecord, MonthlyWorkPackage
from app.services.matching_service import MonthlyPackageNotFoundError, run_matching


ORG = UUID("00000000-0000-0000-0000-000000000001")


def make_package(db_session, *, code_suffix: str = "01"):
    enterprise = Enterprise(
        organization_id=ORG,
        name=f"苏州匹配测试企业{code_suffix}",
        unified_social_credit_code=f"91320500MATCH{code_suffix:0>10}",
        taxpayer_type="GENERAL",
        industry="制造业",
    )
    db_session.add(enterprise)
    db_session.flush()

    package = MonthlyWorkPackage(
        organization_id=ORG,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=int(code_suffix) if code_suffix.isdigit() and 1 <= int(code_suffix) <= 12 else 5,
    )
    db_session.add(package)
    db_session.commit()
    return package


def add_transaction(
    db_session,
    package,
    *,
    transaction_date=date(2026, 5, 8),
    summary="收到货款",
    debit_amount=Decimal("0"),
    credit_amount=Decimal("11300"),
):
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=transaction_date,
        summary=summary,
        credit_amount=credit_amount,
        debit_amount=debit_amount,
    )
    db_session.add(transaction)
    return transaction


def add_invoice(
    db_session,
    package,
    *,
    invoice_direction="OUTPUT",
    invoice_number="INV001",
    invoice_date=date(2026, 5, 6),
    total_amount=Decimal("11300"),
):
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction=invoice_direction,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        amount=Decimal("10000"),
        tax_amount=total_amount - Decimal("10000"),
        total_amount=total_amount,
    )
    db_session.add(invoice)
    return invoice


def test_exact_amount_and_date_match(db_session):
    package = make_package(db_session, code_suffix="01")
    add_transaction(db_session, package)
    add_invoice(db_session, package)
    db_session.commit()

    result = run_matching(db_session, monthly_work_package_id=package.id)

    match = db_session.query(MatchRecord).one()
    db_session.refresh(package)
    assert result["exact_matches"] == 1
    assert result["pending_confirmations"] == 0
    assert match.match_method == "AUTO_EXACT"
    assert match.confidence == 95
    assert match.confirmation_status == "AUTO_CONFIRMED"
    assert package.pending_confirmation_count == 0


def test_output_invoice_matches_bank_credit_amount(db_session):
    package = make_package(db_session, code_suffix="02")
    transaction = add_transaction(db_session, package, credit_amount=Decimal("5650"), debit_amount=Decimal("0"))
    invoice = add_invoice(
        db_session,
        package,
        invoice_direction="OUTPUT",
        invoice_number="OUT-CREDIT",
        total_amount=Decimal("5650"),
    )
    db_session.commit()

    run_matching(db_session, monthly_work_package_id=package.id)

    match = db_session.query(MatchRecord).one()
    assert match.bank_transaction_id == transaction.id
    assert match.invoice_id == invoice.id


def test_input_invoice_matches_bank_debit_amount(db_session):
    package = make_package(db_session, code_suffix="03")
    transaction = add_transaction(
        db_session,
        package,
        summary="支付采购款",
        credit_amount=Decimal("0"),
        debit_amount=Decimal("5650"),
    )
    invoice = add_invoice(
        db_session,
        package,
        invoice_direction="INPUT",
        invoice_number="IN-DEBIT",
        total_amount=Decimal("5650"),
    )
    db_session.commit()

    run_matching(db_session, monthly_work_package_id=package.id)

    match = db_session.query(MatchRecord).one()
    assert match.bank_transaction_id == transaction.id
    assert match.invoice_id == invoice.id


def test_exact_match_only_within_seven_days(db_session):
    package = make_package(db_session, code_suffix="04")
    add_transaction(db_session, package, transaction_date=date(2026, 5, 15))
    add_invoice(db_session, package, invoice_date=date(2026, 5, 7))
    db_session.commit()

    result = run_matching(db_session, monthly_work_package_id=package.id)

    assert result["exact_matches"] == 0
    assert result["pending_confirmations"] == 2
    assert db_session.query(MatchRecord).count() == 0


def test_tax_payment_becomes_accounting_line(db_session):
    package = make_package(db_session, code_suffix="05")
    add_transaction(
        db_session,
        package,
        transaction_date=date(2026, 5, 12),
        summary="缴纳增值税",
        credit_amount=Decimal("0"),
        debit_amount=Decimal("2300"),
    )
    db_session.commit()

    result = run_matching(db_session, monthly_work_package_id=package.id)

    line = db_session.query(AccountingLine).one()
    assert result["rule_lines"] == 1
    assert line.business_type == "TAX_PAYMENT"
    assert line.direction == "TAX"
    assert line.include_category == "TAX"
    assert line.amount == Decimal("2300.00")


def test_matching_is_idempotent_for_matches_and_rule_lines(db_session):
    package = make_package(db_session, code_suffix="06")
    add_transaction(db_session, package)
    add_invoice(db_session, package)
    add_transaction(
        db_session,
        package,
        transaction_date=date(2026, 5, 12),
        summary="银行手续费",
        credit_amount=Decimal("0"),
        debit_amount=Decimal("25"),
    )
    db_session.commit()

    first = run_matching(db_session, monthly_work_package_id=package.id)
    second = run_matching(db_session, monthly_work_package_id=package.id)

    assert first["exact_matches"] == 1
    assert first["rule_lines"] == 1
    assert second["exact_matches"] == 0
    assert second["rule_lines"] == 0
    assert db_session.query(MatchRecord).count() == 1
    assert db_session.query(AccountingLine).count() == 1


def test_missing_package_raises_domain_not_found_error(db_session):
    with pytest.raises(MonthlyPackageNotFoundError, match="Monthly work package not found"):
        run_matching(db_session, monthly_work_package_id=UUID("00000000-0000-0000-0000-000000000099"))
