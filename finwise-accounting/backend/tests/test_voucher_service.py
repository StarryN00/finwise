from datetime import date
from decimal import Decimal
from uuid import UUID

from app.models import (
    AccountSubject,
    BankTransaction,
    Enterprise,
    Invoice,
    MatchRecord,
    MonthlyWorkPackage,
    Voucher,
    VoucherEntry,
    VoucherRule,
)
from app.services.voucher_service import (
    ensure_enterprise_subjects,
    generate_voucher_drafts,
    list_package_vouchers,
    update_single_source_voucher_treatment,
    validate_voucher,
)


ORG = UUID("00000000-0000-0000-0000-000000000001")


def make_enterprise(db_session):
    enterprise = Enterprise(
        organization_id=ORG,
        name="苏州凭证测试有限公司",
        unified_social_credit_code="91320500VOUCHER0001",
        taxpayer_type="SMALL",
        industry="服务业",
    )
    db_session.add(enterprise)
    db_session.commit()
    return enterprise


def make_package(db_session):
    enterprise = make_enterprise(db_session)
    package = MonthlyWorkPackage(
        organization_id=ORG,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
    )
    db_session.add(package)
    db_session.commit()
    return package


def voucher_entries_by_line(voucher):
    return [
        (entry.line_no, entry.direction, entry.account_code, entry.amount)
        for entry in voucher.entries
    ]


def add_confirmed_match(
    db_session,
    package,
    *,
    invoice_direction,
    invoice_number,
    invoice_amount,
    tax_amount,
    total_amount,
    debit_amount,
    credit_amount,
    summary,
):
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction=invoice_direction,
        invoice_number=invoice_number,
        invoice_date=date(2026, 5, 10),
        amount=invoice_amount,
        tax_amount=tax_amount,
        total_amount=total_amount,
    )
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 12),
        summary=summary,
        debit_amount=debit_amount,
        credit_amount=credit_amount,
    )
    db_session.add_all([invoice, transaction])
    db_session.flush()
    db_session.add(
        MatchRecord(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            bank_transaction_id=transaction.id,
            invoice_id=invoice.id,
            match_method="AUTO_EXACT",
            confidence=95,
            explanation="测试确认",
            confirmation_status="AUTO_CONFIRMED",
        )
    )
    db_session.commit()


def make_manual_voucher(db_session, package, *, voucher_date=date(2026, 5, 20), lines):
    subjects = ensure_enterprise_subjects(db_session, enterprise_id=package.enterprise_id)
    account_names = {subject.code: subject.name for subject in subjects}
    voucher = Voucher(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        voucher_date=voucher_date,
        summary="手工校验凭证",
        source_key=f"manual:{len(lines)}:{voucher_date.isoformat()}",
        source_data={},
        ai_confidence=0,
        ai_reason="测试",
    )
    voucher.entries = [
        VoucherEntry(
            organization_id=ORG,
            line_no=index,
            direction=direction,
            account_code=account_code,
            account_name=account_names.get(account_code, ""),
            amount=amount,
            source_type="TEST",
            source_id=str(index),
        )
        for index, (direction, account_code, amount) in enumerate(lines, start=1)
    ]
    db_session.add(voucher)
    db_session.flush()
    return voucher


def test_ensure_enterprise_subjects_creates_small_business_template(db_session):
    enterprise = make_enterprise(db_session)

    subjects = ensure_enterprise_subjects(db_session, enterprise_id=enterprise.id)

    codes = {subject.code for subject in subjects}
    assert "1002" in codes
    assert "1122" in codes
    assert "1123" in codes
    assert "2202" in codes
    assert "2203" in codes
    assert "22210101" in codes
    assert "22210102" in codes
    assert "5001" in codes
    assert "560201" in codes
    assert all(subject.organization_id == ORG for subject in subjects)
    assert all(subject.enterprise_id == enterprise.id for subject in subjects)

    subjects_again = ensure_enterprise_subjects(db_session, enterprise_id=enterprise.id)
    codes_again = [subject.code for subject in subjects_again]

    assert len(subjects_again) == len(subjects)
    assert len(codes_again) == len(set(codes_again))


def test_generate_voucher_drafts_for_matched_output_invoice_receipt(db_session):
    package = make_package(db_session)
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-VOUCHER-001",
        invoice_date=date(2026, 5, 10),
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
    )
    db_session.add(invoice)
    db_session.flush()
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 12),
        summary="收到客户货款",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("1130.00"),
    )
    db_session.add(transaction)
    db_session.flush()
    db_session.add(
        MatchRecord(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            bank_transaction_id=transaction.id,
            invoice_id=invoice.id,
            match_method="AUTO_EXACT",
            confidence=95,
            explanation="测试确认",
            confirmation_status="AUTO_CONFIRMED",
        )
    )
    db_session.commit()

    result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)

    assert result["created_vouchers"] == 1
    voucher = result["vouchers"][0]
    assert voucher.summary == "确认销售收入并收款"
    assert voucher.status == "PENDING_CONFIRMATION"
    assert voucher.ai_confidence == 92
    assert voucher.validation_errors == []
    assert voucher_entries_by_line(voucher) == [
        (1, "DEBIT", "1002", Decimal("1130.00")),
        (2, "CREDIT", "5001", Decimal("1000.00")),
        (3, "CREDIT", "22210102", Decimal("130.00")),
    ]
    assert voucher.source_data["bank_transaction"]["summary"] == "收到客户货款"
    assert voucher.source_data["bank_transaction"]["credit_amount"] == "1130.00"
    assert voucher.source_data["invoice"]["invoice_number"] == "OUT-VOUCHER-001"
    assert voucher.source_data["invoice"]["total_amount"] == "1130.00"
    assert voucher.source_data["match"]["confidence"] == 95
    assert voucher.source_data["source_group_type"] == "FULL_MATCH"
    assert voucher.source_data["voucher_task_type"] == "FULL_MATCH"

    assert db_session.query(Voucher).count() == 1
    second_result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)
    assert second_result["created_vouchers"] == 0


def test_generate_voucher_drafts_for_difference_completion_match(db_session):
    package = make_package(db_session)
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-DIFF-001",
        invoice_date=date(2026, 5, 10),
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
        seller_name="苏州凭证测试有限公司",
        buyer_name="苏州差额客户有限公司",
    )
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 12),
        summary="收到客户部分货款",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("1000.00"),
        counterparty_name="苏州差额客户有限公司",
    )
    db_session.add_all([invoice, transaction])
    db_session.flush()
    db_session.add(
        MatchRecord(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            bank_transaction_id=transaction.id,
            invoice_id=invoice.id,
            match_method="AI_AMOUNT_DIFF",
            confidence=76,
            explanation="金额不一致但主体和日期接近",
            confirmation_status="CONFIRMED",
        )
    )
    db_session.commit()

    result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)

    assert result["created_vouchers"] == 1
    voucher = result["vouchers"][0]
    assert voucher.summary == "确认销售收入并补齐差额"
    assert voucher.source_data["source_group_type"] == "DIFFERENCE_COMPLETION"
    assert voucher.source_data["voucher_task_type"] == "DIFFERENCE_COMPLETION"
    assert voucher.source_data["difference_amount"] == "130.00"
    assert voucher.validation_errors == []
    assert voucher_entries_by_line(voucher) == [
        (1, "DEBIT", "1002", Decimal("1000.00")),
        (2, "DEBIT", "1122", Decimal("130.00")),
        (3, "CREDIT", "5001", Decimal("1000.00")),
        (4, "CREDIT", "22210102", Decimal("130.00")),
    ]


def test_generate_voucher_drafts_omits_zero_tax_line_for_output_invoice(db_session):
    package = make_package(db_session)
    add_confirmed_match(
        db_session,
        package,
        invoice_direction="OUTPUT",
        invoice_number="OUT-VOUCHER-ZERO-TAX",
        invoice_amount=Decimal("1000.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("1000.00"),
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("1000.00"),
        summary="收到免税客户货款",
    )

    result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)

    assert result["created_vouchers"] == 1
    voucher = result["vouchers"][0]
    assert voucher.validation_errors == []
    assert voucher_entries_by_line(voucher) == [
        (1, "DEBIT", "1002", Decimal("1000.00")),
        (2, "CREDIT", "5001", Decimal("1000.00")),
    ]


def test_generate_voucher_drafts_for_matched_input_invoice_payment(db_session):
    package = make_package(db_session)
    add_confirmed_match(
        db_session,
        package,
        invoice_direction="INPUT",
        invoice_number="IN-VOUCHER-001",
        invoice_amount=Decimal("200.00"),
        tax_amount=Decimal("12.00"),
        total_amount=Decimal("212.00"),
        debit_amount=Decimal("212.00"),
        credit_amount=Decimal("0.00"),
        summary="支付服务费",
    )

    result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)

    assert result["created_vouchers"] == 1
    voucher = result["vouchers"][0]
    assert voucher.summary == "确认费用并付款"
    assert voucher.status == "PENDING_CONFIRMATION"
    assert voucher.ai_confidence == 82
    assert voucher.validation_errors == []
    assert voucher_entries_by_line(voucher) == [
        (1, "DEBIT", "560203", Decimal("200.00")),
        (2, "DEBIT", "22210101", Decimal("12.00")),
        (3, "CREDIT", "1002", Decimal("212.00")),
    ]


def test_generate_voucher_drafts_omits_zero_tax_line_for_input_invoice(db_session):
    package = make_package(db_session)
    add_confirmed_match(
        db_session,
        package,
        invoice_direction="INPUT",
        invoice_number="IN-VOUCHER-ZERO-TAX",
        invoice_amount=Decimal("200.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("200.00"),
        debit_amount=Decimal("200.00"),
        credit_amount=Decimal("0.00"),
        summary="支付免税服务费",
    )

    result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)

    assert result["created_vouchers"] == 1
    voucher = result["vouchers"][0]
    assert voucher.validation_errors == []
    assert voucher_entries_by_line(voucher) == [
        (1, "DEBIT", "560203", Decimal("200.00")),
        (2, "CREDIT", "1002", Decimal("200.00")),
    ]


def test_generate_voucher_drafts_for_unmatched_bank_fee(db_session):
    package = make_package(db_session)
    db_session.add(
        BankTransaction(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            transaction_date=date(2026, 5, 15),
            summary="银行手续费",
            debit_amount=Decimal("12.00"),
            credit_amount=Decimal("0.00"),
            counterparty_name="开户银行",
            raw_row_data={"原始摘要": "银行手续费", "借方发生额": "12.00"},
        )
    )
    db_session.commit()

    result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)

    assert result["created_vouchers"] == 1
    voucher = result["vouchers"][0]
    assert voucher.summary == "支付银行手续费"
    assert voucher.status == "PENDING_CONFIRMATION"
    assert voucher.ai_confidence == 88
    assert voucher.validation_errors == []
    assert voucher_entries_by_line(voucher) == [
        (1, "DEBIT", "560301", Decimal("12.00")),
        (2, "CREDIT", "1002", Decimal("12.00")),
    ]
    assert voucher.source_data["bank_transaction"]["summary"] == "银行手续费"
    assert voucher.source_data["bank_transaction"]["counterparty_name"] == "开户银行"
    assert voucher.source_data["bank_transaction"]["raw_row_data"]["原始摘要"] == "银行手续费"


def test_generate_voucher_drafts_covers_unmatched_invoices_and_bank_transactions(db_session):
    package = make_package(db_session)
    input_invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="INPUT",
        invoice_number="IN-UNMATCHED-001",
        invoice_date=date(2026, 5, 8),
        amount=Decimal("300.00"),
        tax_amount=Decimal("39.00"),
        total_amount=Decimal("339.00"),
        seller_name="测试服务商",
        buyer_name="苏州凭证测试有限公司",
    )
    output_invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-UNMATCHED-001",
        invoice_date=date(2026, 5, 9),
        amount=Decimal("500.00"),
        tax_amount=Decimal("65.00"),
        total_amount=Decimal("565.00"),
        seller_name="苏州凭证测试有限公司",
        buyer_name="测试客户",
    )
    payment = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 10),
        summary="电子转账",
        debit_amount=Decimal("88.00"),
        credit_amount=Decimal("0.00"),
        counterparty_name="未知供应商",
    )
    receipt = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 11),
        summary="电子汇入",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("99.00"),
        counterparty_name="未知客户",
    )
    db_session.add_all([input_invoice, output_invoice, payment, receipt])
    db_session.commit()

    result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)

    assert result["created_vouchers"] == 4
    vouchers_by_source = {voucher.source_key: voucher for voucher in result["vouchers"]}
    input_voucher = vouchers_by_source[f"invoice:{input_invoice.id}"]
    assert input_voucher.summary == "确认费用未付款"
    assert input_voucher.ai_reason == "进项发票暂无匹配银行流水，需人工确认是否已付款或挂应付账款"
    assert voucher_entries_by_line(input_voucher) == [
        (1, "DEBIT", "560203", Decimal("300.00")),
        (2, "DEBIT", "22210101", Decimal("39.00")),
        (3, "CREDIT", "2202", Decimal("339.00")),
    ]

    output_voucher = vouchers_by_source[f"invoice:{output_invoice.id}"]
    assert output_voucher.summary == "确认销售收入未收款"
    assert voucher_entries_by_line(output_voucher) == [
        (1, "DEBIT", "1122", Decimal("565.00")),
        (2, "CREDIT", "5001", Decimal("500.00")),
        (3, "CREDIT", "22210102", Decimal("65.00")),
    ]

    payment_voucher = vouchers_by_source[f"bank:{payment.id}"]
    assert payment_voucher.summary == "记录银行付款待补发票"
    assert voucher_entries_by_line(payment_voucher) == [
        (1, "DEBIT", "1123", Decimal("88.00")),
        (2, "CREDIT", "1002", Decimal("88.00")),
    ]

    receipt_voucher = vouchers_by_source[f"bank:{receipt.id}"]
    assert receipt_voucher.summary == "记录银行收款待补发票"
    assert voucher_entries_by_line(receipt_voucher) == [
        (1, "DEBIT", "1002", Decimal("99.00")),
        (2, "CREDIT", "2203", Decimal("99.00")),
    ]

    second_result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)
    assert second_result["created_vouchers"] == 0


def test_generate_voucher_drafts_refreshes_existing_pending_single_bank_voucher_defaults(db_session):
    package = make_package(db_session)
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 10),
        summary="电子转账",
        debit_amount=Decimal("88.00"),
        credit_amount=Decimal("0.00"),
        counterparty_name="未知供应商",
    )
    db_session.add(transaction)
    db_session.flush()
    voucher = make_manual_voucher(
        db_session,
        package,
        voucher_date=transaction.transaction_date,
        lines=[
            ("DEBIT", "560203", Decimal("88.00")),
            ("CREDIT", "1002", Decimal("88.00")),
        ],
    )
    voucher.summary = "记录银行付款待补发票"
    voucher.source_key = f"bank:{transaction.id}"
    voucher.source_data = {
        "bank_transaction_id": str(transaction.id),
        "bank_transaction": {"id": str(transaction.id)},
    }
    voucher.ai_reason = "旧版本直接暂估费用"
    db_session.commit()

    result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)

    assert result["created_vouchers"] == 0
    db_session.refresh(voucher)
    assert voucher.ai_reason == "银行付款暂无匹配发票，先按预付账款暂挂，需人工确认业务归属或重新匹配发票"
    assert voucher_entries_by_line(voucher) == [
        (1, "DEBIT", "1123", Decimal("88.00")),
        (2, "CREDIT", "1002", Decimal("88.00")),
    ]


def test_generate_voucher_drafts_groups_one_invoice_paid_by_multiple_bank_transactions(db_session):
    package = make_package(db_session)
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="INPUT",
        invoice_number="IN-GROUP-001",
        invoice_date=date(2026, 5, 8),
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
        seller_name="分次付款供应商",
    )
    first_payment = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 10),
        summary="第一笔付款",
        debit_amount=Decimal("500.00"),
        credit_amount=Decimal("0.00"),
        counterparty_name="分次付款供应商",
    )
    second_payment = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 11),
        summary="第二笔付款",
        debit_amount=Decimal("630.00"),
        credit_amount=Decimal("0.00"),
        counterparty_name="分次付款供应商",
    )
    db_session.add_all([invoice, first_payment, second_payment])
    db_session.flush()
    for transaction in (first_payment, second_payment):
        db_session.add(
            MatchRecord(
                organization_id=ORG,
                monthly_work_package_id=package.id,
                bank_transaction_id=transaction.id,
                invoice_id=invoice.id,
                match_group_id="group-one-invoice",
                match_method="AI_GROUPED",
                confidence=88,
                explanation="发票金额由多笔付款合计匹配",
                confirmation_status="CONFIRMED",
            )
        )
    db_session.commit()

    result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)

    assert result["created_vouchers"] == 1
    voucher = result["vouchers"][0]
    assert voucher.summary == "确认费用并分次付款"
    assert voucher.source_data["source_group_type"] == "ONE_INVOICE_MULTIPLE_BANK_TRANSACTIONS"
    assert len(voucher.source_data["bank_transactions"]) == 2
    assert voucher.source_data["invoice"]["invoice_number"] == "IN-GROUP-001"
    assert voucher_entries_by_line(voucher) == [
        (1, "DEBIT", "560203", Decimal("1000.00")),
        (2, "DEBIT", "22210101", Decimal("130.00")),
        (3, "CREDIT", "1002", Decimal("1130.00")),
    ]


def test_generate_voucher_drafts_groups_one_bank_transaction_for_multiple_output_invoices(db_session):
    package = make_package(db_session)
    first_invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-GROUP-001",
        invoice_date=date(2026, 5, 8),
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
        buyer_name="合并付款客户",
    )
    second_invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-GROUP-002",
        invoice_date=date(2026, 5, 9),
        amount=Decimal("2000.00"),
        tax_amount=Decimal("260.00"),
        total_amount=Decimal("2260.00"),
        buyer_name="合并付款客户",
    )
    receipt = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 12),
        summary="客户合并付款",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("3390.00"),
        counterparty_name="合并付款客户",
    )
    db_session.add_all([first_invoice, second_invoice, receipt])
    db_session.flush()
    for invoice in (first_invoice, second_invoice):
        db_session.add(
            MatchRecord(
                organization_id=ORG,
                monthly_work_package_id=package.id,
                bank_transaction_id=receipt.id,
                invoice_id=invoice.id,
                match_group_id="group-one-bank",
                match_method="AI_GROUPED",
                confidence=87,
                explanation="银行收款由多张发票合计匹配",
                confirmation_status="CONFIRMED",
            )
        )
    db_session.commit()

    result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)

    assert result["created_vouchers"] == 1
    voucher = result["vouchers"][0]
    assert voucher.summary == "确认多张销售发票并收款"
    assert voucher.source_data["source_group_type"] == "ONE_BANK_TRANSACTION_MULTIPLE_INVOICES"
    assert voucher.source_data["bank_transaction"]["summary"] == "客户合并付款"
    assert len(voucher.source_data["invoices"]) == 2
    assert voucher_entries_by_line(voucher) == [
        (1, "DEBIT", "1002", Decimal("3390.00")),
        (2, "CREDIT", "5001", Decimal("3000.00")),
        (3, "CREDIT", "22210102", Decimal("390.00")),
    ]


def test_list_package_vouchers_enriches_legacy_source_ids(db_session):
    package = make_package(db_session)
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 15),
        summary="支付银行手续费",
        debit_amount=Decimal("4.50"),
        credit_amount=Decimal("0.00"),
        counterparty_name="银行",
    )
    db_session.add(transaction)
    db_session.flush()
    voucher = make_manual_voucher(
        db_session,
        package,
        voucher_date=date(2026, 5, 15),
        lines=[
            ("DEBIT", "560301", Decimal("4.50")),
            ("CREDIT", "1002", Decimal("4.50")),
        ],
    )
    voucher.source_key = f"bank:{transaction.id}"
    voucher.source_data = {"bank_transaction_id": str(transaction.id)}
    db_session.commit()

    listed_voucher = list_package_vouchers(db_session, monthly_work_package_id=package.id)[0]

    assert listed_voucher.source_data["bank_transaction"]["summary"] == "支付银行手续费"
    assert listed_voucher.source_data["bank_transaction"]["debit_amount"] == "4.50"
    assert listed_voucher.source_data["bank_transaction"]["counterparty_name"] == "银行"


def test_generate_voucher_drafts_ignores_cross_package_match_sources(db_session):
    enterprise = make_enterprise(db_session)
    target_package = MonthlyWorkPackage(
        organization_id=ORG,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
    )
    other_package = MonthlyWorkPackage(
        organization_id=ORG,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=6,
    )
    db_session.add_all([target_package, other_package])
    db_session.commit()
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=other_package.id,
        transaction_date=date(2026, 5, 12),
        summary="其他期间收款",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("1130.00"),
    )
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=other_package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-CROSS-PACKAGE",
        invoice_date=date(2026, 5, 10),
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
    )
    db_session.add_all([transaction, invoice])
    db_session.flush()
    db_session.add(
        MatchRecord(
            organization_id=ORG,
            monthly_work_package_id=target_package.id,
            bank_transaction_id=transaction.id,
            invoice_id=invoice.id,
            match_method="MANUAL",
            confidence=95,
            explanation="跨包脏数据",
            confirmation_status="CONFIRMED",
        )
    )
    db_session.commit()

    result = generate_voucher_drafts(db_session, monthly_work_package_id=target_package.id)

    assert result["created_vouchers"] == 0
    assert db_session.query(Voucher).count() == 0


def test_generate_voucher_drafts_bank_fee_ignores_dirty_cross_package_match(db_session):
    enterprise = make_enterprise(db_session)
    target_package = MonthlyWorkPackage(
        organization_id=ORG,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
    )
    other_package = MonthlyWorkPackage(
        organization_id=ORG,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=6,
    )
    db_session.add_all([target_package, other_package])
    db_session.commit()
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=target_package.id,
        transaction_date=date(2026, 5, 15),
        summary="银行手续费",
        debit_amount=Decimal("12.00"),
        credit_amount=Decimal("0.00"),
    )
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=other_package.id,
        invoice_direction="INPUT",
        invoice_number="IN-CROSS-PACKAGE",
        invoice_date=date(2026, 6, 10),
        amount=Decimal("12.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("12.00"),
    )
    db_session.add_all([transaction, invoice])
    db_session.flush()
    db_session.add(
        MatchRecord(
            organization_id=ORG,
            monthly_work_package_id=target_package.id,
            bank_transaction_id=transaction.id,
            invoice_id=invoice.id,
            match_method="MANUAL",
            confidence=95,
            explanation="跨包脏数据",
            confirmation_status="CONFIRMED",
        )
    )
    db_session.commit()

    result = generate_voucher_drafts(db_session, monthly_work_package_id=target_package.id)

    assert result["created_vouchers"] == 1
    assert result["vouchers"][0].summary == "支付银行手续费"
    assert voucher_entries_by_line(result["vouchers"][0]) == [
        (1, "DEBIT", "560301", Decimal("12.00")),
        (2, "CREDIT", "1002", Decimal("12.00")),
    ]


def test_validate_voucher_flags_debit_credit_mismatch(db_session):
    package = make_package(db_session)
    voucher = make_manual_voucher(
        db_session,
        package,
        lines=[
            ("DEBIT", "1002", Decimal("10.00")),
            ("CREDIT", "5001", Decimal("9.00")),
        ],
    )

    assert "DEBIT_CREDIT_NOT_EQUAL" in validate_voucher(db_session, voucher)


def test_validate_voucher_flags_disabled_subject(db_session):
    package = make_package(db_session)
    ensure_enterprise_subjects(db_session, enterprise_id=package.enterprise_id)
    subject = (
        db_session.query(AccountSubject)
        .filter(AccountSubject.enterprise_id == package.enterprise_id, AccountSubject.code == "1002")
        .one()
    )
    subject.is_enabled = False
    db_session.commit()
    voucher = make_manual_voucher(
        db_session,
        package,
        lines=[
            ("DEBIT", "1002", Decimal("10.00")),
            ("CREDIT", "5001", Decimal("10.00")),
        ],
    )

    assert "SUBJECT_NOT_ENABLED" in validate_voucher(db_session, voucher)


def test_validate_voucher_flags_non_leaf_subject(db_session):
    package = make_package(db_session)
    voucher = make_manual_voucher(
        db_session,
        package,
        lines=[
            ("DEBIT", "2221", Decimal("10.00")),
            ("CREDIT", "1002", Decimal("10.00")),
        ],
    )

    errors = validate_voucher(db_session, voucher)
    assert "SUBJECT_NOT_LEAF" in errors


def test_validate_voucher_flags_missing_subject(db_session):
    package = make_package(db_session)
    voucher = make_manual_voucher(
        db_session,
        package,
        lines=[
            ("DEBIT", "999999", Decimal("10.00")),
            ("CREDIT", "1002", Decimal("10.00")),
        ],
    )

    errors = validate_voucher(db_session, voucher)
    assert "SUBJECT_NOT_ENABLED" in errors
    assert "SUBJECT_NOT_LEAF" in errors


def test_validate_voucher_flags_zero_amount(db_session):
    package = make_package(db_session)
    voucher = make_manual_voucher(
        db_session,
        package,
        lines=[
            ("DEBIT", "1002", Decimal("0.00")),
            ("CREDIT", "5001", Decimal("0.00")),
        ],
    )

    assert "ZERO_AMOUNT" in validate_voucher(db_session, voucher)


def test_validate_voucher_flags_date_outside_period(db_session):
    package = make_package(db_session)
    voucher = make_manual_voucher(
        db_session,
        package,
        voucher_date=date(2026, 6, 1),
        lines=[
            ("DEBIT", "1002", Decimal("10.00")),
            ("CREDIT", "5001", Decimal("10.00")),
        ],
    )

    assert "DATE_OUT_OF_PERIOD" in validate_voucher(db_session, voucher)


def test_adjusting_single_source_treatment_records_voucher_rule(db_session):
    package = make_package(db_session)
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 12),
        summary="客户预付款",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("500.00"),
        counterparty_name="苏州规则客户有限公司",
    )
    db_session.add(transaction)
    db_session.commit()
    result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)
    voucher = result["vouchers"][0]

    update_single_source_voucher_treatment(
        db_session,
        voucher_id=voucher.id,
        treatment_type="预收账款暂挂",
        summary="记录银行收款待补发票",
        debit_account_code="1002",
        credit_account_code="2203",
        note="客户确认按预收处理",
    )

    rules = db_session.query(VoucherRule).filter(VoucherRule.enterprise_id == package.enterprise_id).all()
    assert len(rules) == 1
    rule = rules[0]
    assert rule.rule_name == "预收账款暂挂-苏州规则客户有限公司"
    assert rule.counterparty_pattern == "苏州规则客户有限公司"
    assert rule.source_direction == "INFLOW"
    assert rule.summary_keywords == ["客户预付款"]
    assert rule.summary_template == "记录银行收款待补发票"
    assert rule.debit_account_code == "1002"
    assert rule.credit_account_code == "2203"
