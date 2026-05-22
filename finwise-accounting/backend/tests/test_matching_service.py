from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.models import AccountingLine, BankTransaction, Enterprise, Invoice, MatchRecord, MatchingRule, MonthlyWorkPackage
from app.api.deps import get_db
from app.main import create_app
from app.services.matching_service import (
    MonthlyPackageNotFoundError,
    create_enterprise_matching_rule,
    run_matching,
)


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
    counterparty_name=None,
):
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=transaction_date,
        summary=summary,
        credit_amount=credit_amount,
        debit_amount=debit_amount,
        counterparty_name=counterparty_name,
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
    assert result["pending_confirmations"] == 1
    assert line.business_type == "TAX_PAYMENT"
    assert line.direction == "TAX"
    assert line.include_category == "TAX"
    assert line.amount == Decimal("2300.00")


def test_persisted_enterprise_rule_creates_accounting_line(db_session):
    package = make_package(db_session, code_suffix="07")
    create_enterprise_matching_rule(
        db_session,
        enterprise_id=package.enterprise_id,
        summary_keywords=["云服务"],
        suggested_business_type="CLOUD_SERVICE",
    )
    add_transaction(
        db_session,
        package,
        transaction_date=date(2026, 5, 13),
        summary="支付云服务订阅费",
        credit_amount=Decimal("0"),
        debit_amount=Decimal("880"),
    )
    db_session.commit()

    result = run_matching(db_session, monthly_work_package_id=package.id)

    line = db_session.query(AccountingLine).one()
    assert result["rule_lines"] == 1
    assert result["pending_confirmations"] == 1
    assert line.business_type == "CLOUD_SERVICE"
    assert line.direction == "EXPENSE"
    assert line.include_category == "EXPENSE"


def test_built_in_rules_run_before_persisted_rules(db_session):
    package = make_package(db_session, code_suffix="08")
    create_enterprise_matching_rule(
        db_session,
        enterprise_id=package.enterprise_id,
        summary_keywords=["增值税"],
        suggested_business_type="CUSTOM_TAX_MEMORY",
    )
    add_transaction(
        db_session,
        package,
        transaction_date=date(2026, 5, 13),
        summary="缴纳增值税",
        credit_amount=Decimal("0"),
        debit_amount=Decimal("2300"),
    )
    db_session.commit()

    run_matching(db_session, monthly_work_package_id=package.id)

    line = db_session.query(AccountingLine).one()
    assert line.business_type == "TAX_PAYMENT"


def test_confirm_only_pending_accounting_line_updates_package_status(db_session):
    package = make_package(db_session, code_suffix="09")
    add_transaction(
        db_session,
        package,
        transaction_date=date(2026, 5, 12),
        summary="银行手续费",
        credit_amount=Decimal("0"),
        debit_amount=Decimal("25"),
    )
    db_session.commit()
    run_matching(db_session, monthly_work_package_id=package.id)
    line = db_session.query(AccountingLine).one()

    app = create_app(init_db_on_startup=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.post(f"/api/accounting-lines/{line.id}/confirm")

    db_session.refresh(package)
    assert response.status_code == 200
    assert response.json()["confirmation_status"] == "CONFIRMED"
    assert package.pending_confirmation_count == 0
    assert package.matching_status == "CONFIRMED"


def test_confirm_accounting_line_with_save_as_rule_creates_matching_rule(db_session):
    package = make_package(db_session, code_suffix="10")
    transaction = add_transaction(
        db_session,
        package,
        transaction_date=date(2026, 5, 12),
        summary="支付云服务订阅费",
        credit_amount=Decimal("0"),
        debit_amount=Decimal("880"),
        counterparty_name="阿里云计算有限公司",
    )
    db_session.flush()
    line = AccountingLine(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        source_type="BANK_TRANSACTION",
        source_id=str(transaction.id),
        business_type="CLOUD_SERVICE",
        direction="EXPENSE",
        amount=Decimal("880"),
        tax_amount=Decimal("0"),
        include_category="EXPENSE",
        confirmation_status="PENDING",
    )
    db_session.add(line)
    db_session.commit()

    app = create_app(init_db_on_startup=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.post(f"/api/accounting-lines/{line.id}/confirm", json={"save_as_rule": True})

    rule = db_session.query(MatchingRule).one()
    assert response.status_code == 200
    assert response.json()["rule_id"] == str(rule.id)
    assert rule.enterprise_id == package.enterprise_id
    assert rule.scope == "ENTERPRISE"
    assert rule.source == "USER_CONFIRMED"
    assert rule.summary_keywords == ["云服务"]
    assert rule.counterparty_pattern == "阿里云计算有限公司"
    assert rule.suggested_business_type == "CLOUD_SERVICE"


def test_confirmed_rule_is_reused_for_later_similar_transaction(db_session):
    package = make_package(db_session, code_suffix="11")
    transaction = add_transaction(
        db_session,
        package,
        transaction_date=date(2026, 5, 12),
        summary="支付云服务订阅费",
        credit_amount=Decimal("0"),
        debit_amount=Decimal("880"),
        counterparty_name="阿里云计算有限公司",
    )
    db_session.flush()
    line = AccountingLine(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        source_type="BANK_TRANSACTION",
        source_id=str(transaction.id),
        business_type="CLOUD_SERVICE",
        direction="EXPENSE",
        amount=Decimal("880"),
        tax_amount=Decimal("0"),
        include_category="EXPENSE",
        confirmation_status="PENDING",
    )
    db_session.add(line)
    db_session.commit()

    app = create_app(init_db_on_startup=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    client.post(f"/api/accounting-lines/{line.id}/confirm", json={"save_as_rule": True})

    later_package = MonthlyWorkPackage(
        organization_id=ORG,
        enterprise_id=package.enterprise_id,
        period_year=2026,
        period_month=12,
    )
    db_session.add(later_package)
    db_session.flush()
    add_transaction(
        db_session,
        later_package,
        transaction_date=date(2026, 12, 10),
        summary="支付云服务年度订阅",
        credit_amount=Decimal("0"),
        debit_amount=Decimal("1280"),
        counterparty_name="阿里云计算有限公司",
    )
    db_session.commit()

    result = run_matching(db_session, monthly_work_package_id=later_package.id)

    later_line = db_session.query(AccountingLine).filter(AccountingLine.monthly_work_package_id == later_package.id).one()
    assert result["rule_lines"] == 1
    assert later_line.business_type == "CLOUD_SERVICE"
    assert later_line.include_category == "EXPENSE"


def test_confirm_accounting_line_without_save_as_rule_does_not_create_rule(db_session):
    package = make_package(db_session, code_suffix="12")
    transaction = add_transaction(
        db_session,
        package,
        transaction_date=date(2026, 5, 12),
        summary="支付云服务订阅费",
        credit_amount=Decimal("0"),
        debit_amount=Decimal("880"),
    )
    db_session.flush()
    line = AccountingLine(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        source_type="BANK_TRANSACTION",
        source_id=str(transaction.id),
        business_type="CLOUD_SERVICE",
        direction="EXPENSE",
        amount=Decimal("880"),
        tax_amount=Decimal("0"),
        include_category="EXPENSE",
        confirmation_status="PENDING",
    )
    db_session.add(line)
    db_session.commit()

    app = create_app(init_db_on_startup=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.post(f"/api/accounting-lines/{line.id}/confirm", json={"save_as_rule": False})

    assert response.status_code == 200
    assert "rule_id" not in response.json()
    assert db_session.query(MatchingRule).count() == 0


def test_confirm_ineligible_accounting_line_with_save_as_rule_returns_400(db_session):
    package = make_package(db_session, code_suffix="13")
    line = AccountingLine(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        source_type="MANUAL",
        source_id="manual-line",
        business_type="MANUAL_ADJUSTMENT",
        direction="EXPENSE",
        amount=Decimal("100"),
        tax_amount=Decimal("0"),
        include_category="EXPENSE",
        confirmation_status="PENDING",
    )
    db_session.add(line)
    db_session.commit()

    app = create_app(init_db_on_startup=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(f"/api/accounting-lines/{line.id}/confirm", json={"save_as_rule": True})

    assert response.status_code == 400
    assert db_session.query(MatchingRule).count() == 0


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
