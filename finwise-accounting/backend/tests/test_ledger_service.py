from datetime import date
from decimal import Decimal
from uuid import UUID

from app.models import Enterprise, HistoricalBalanceRow, HistoricalImportBatch, MonthlyWorkPackage, Voucher, VoucherEntry
from app.services.ledger_service import LedgerService


ORG = UUID("00000000-0000-0000-0000-000000000001")


def money(value: str) -> Decimal:
    return Decimal(value)


def make_package(db_session):
    enterprise = Enterprise(
        organization_id=ORG,
        name="苏州账簿测试有限公司",
        unified_social_credit_code="91320500LEDGER0001",
        taxpayer_type="GENERAL",
        industry="制造业",
    )
    db_session.add(enterprise)
    db_session.flush()
    package = MonthlyWorkPackage(
        organization_id=ORG,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=4,
    )
    db_session.add(package)
    db_session.commit()
    return package


def add_voucher(db_session, package, *, number, voucher_date, status, entries, source_data=None):
    voucher = Voucher(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        voucher_date=voucher_date,
        voucher_number=number,
        summary=f"摘要{number or '未编号'}",
        source_key=f"ledger-test:{number or 'pending'}:{voucher_date.isoformat()}:{len(entries)}",
        source_data=source_data or {},
        ai_confidence=90,
        status=status,
    )
    db_session.add(voucher)
    db_session.flush()
    for line_no, (direction, account_code, account_name, amount) in enumerate(entries, start=1):
        db_session.add(
            VoucherEntry(
                organization_id=ORG,
                voucher_id=voucher.id,
                line_no=line_no,
                direction=direction,
                account_code=account_code,
                account_name=account_name,
                amount=money(amount),
                source_type="TEST",
                source_id=f"{voucher.id}:{line_no}",
            )
        )
    db_session.commit()
    return voucher


def add_historical_balance(
    db_session,
    package,
    *,
    account_code,
    account_name,
    opening_debit="0.00",
    opening_credit="0.00",
    closing_debit="0.00",
    closing_credit="0.00",
):
    batch = HistoricalImportBatch(
        organization_id=ORG,
        enterprise_id=package.enterprise_id,
        fiscal_year=package.period_year,
        ledger_filename="ledger.xlsx",
        balance_filename="balance.xlsx",
    )
    db_session.add(batch)
    db_session.flush()
    row = HistoricalBalanceRow(
        organization_id=ORG,
        enterprise_id=package.enterprise_id,
        import_batch_id=batch.id,
        fiscal_year=package.period_year,
        account_code=account_code,
        account_name=account_name,
        opening_debit=money(opening_debit),
        opening_credit=money(opening_credit),
        closing_debit=money(closing_debit),
        closing_credit=money(closing_credit),
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_journal_uses_only_confirmed_vouchers_and_sorts_rows(db_session):
    package = make_package(db_session)
    add_voucher(
        db_session,
        package,
        number="记-0002",
        voucher_date=date(2026, 4, 2),
        status="CONFIRMED",
        entries=[
            ("DEBIT", "1002", "银行存款", "200.00"),
            ("CREDIT", "5001", "主营业务收入", "200.00"),
        ],
    )
    add_voucher(
        db_session,
        package,
        number="记-0001",
        voucher_date=date(2026, 4, 1),
        status="CONFIRMED",
        entries=[
            ("DEBIT", "560203", "服务费", "100.00"),
            ("CREDIT", "1002", "银行存款", "100.00"),
        ],
    )
    add_voucher(
        db_session,
        package,
        number=None,
        voucher_date=date(2026, 4, 3),
        status="PENDING_CONFIRMATION",
        entries=[
            ("DEBIT", "560203", "服务费", "300.00"),
            ("CREDIT", "1002", "银行存款", "300.00"),
        ],
    )

    rows = LedgerService(db_session).get_journal(package.id)

    assert [row.voucher_number for row in rows] == ["记-0001", "记-0001", "记-0002", "记-0002"]
    assert rows[0].account_code == "560203"
    assert rows[0].debit_amount == money("100.00")
    assert rows[1].credit_amount == money("100.00")


def test_general_ledger_groups_current_period_amounts(db_session):
    package = make_package(db_session)
    add_voucher(
        db_session,
        package,
        number="记-0001",
        voucher_date=date(2026, 4, 1),
        status="CONFIRMED",
        entries=[
            ("DEBIT", "1002", "银行存款", "200.00"),
            ("CREDIT", "5001", "主营业务收入", "200.00"),
        ],
    )
    add_voucher(
        db_session,
        package,
        number="记-0002",
        voucher_date=date(2026, 4, 2),
        status="CONFIRMED",
        entries=[
            ("DEBIT", "560203", "服务费", "50.00"),
            ("CREDIT", "1002", "银行存款", "50.00"),
        ],
    )

    rows = {row.account_code: row for row in LedgerService(db_session).get_general(package.id)}

    assert rows["1002"].period_debit == money("200.00")
    assert rows["1002"].period_credit == money("50.00")
    assert rows["1002"].closing_debit == money("150.00")
    assert rows["5001"].closing_credit == money("200.00")
    assert rows["560203"].closing_debit == money("50.00")


def test_detail_ledger_calculates_running_balance_and_counter_accounts(db_session):
    package = make_package(db_session)
    add_voucher(
        db_session,
        package,
        number="记-0001",
        voucher_date=date(2026, 4, 1),
        status="CONFIRMED",
        entries=[
            ("DEBIT", "1002", "银行存款", "200.00"),
            ("CREDIT", "5001", "主营业务收入", "200.00"),
        ],
    )
    add_voucher(
        db_session,
        package,
        number="记-0002",
        voucher_date=date(2026, 4, 2),
        status="CONFIRMED",
        entries=[
            ("DEBIT", "560203", "服务费", "50.00"),
            ("CREDIT", "1002", "银行存款", "50.00"),
        ],
    )

    rows = LedgerService(db_session).get_detail(package.id, "1002")

    assert rows[0].balance == money("200.00")
    assert rows[0].counter_accounts == "主营业务收入"
    assert rows[1].balance == money("150.00")
    assert rows[1].counter_accounts == "服务费"


def test_detail_ledger_displays_counterparty_auxiliary_for_current_accounts(db_session):
    package = make_package(db_session)
    add_voucher(
        db_session,
        package,
        number="记-0003",
        voucher_date=date(2026, 4, 3),
        status="CONFIRMED",
        source_data={"bank_transaction": {"counterparty_name": "上海安费诺永亿通讯电子有限公司"}},
        entries=[
            ("DEBIT", "1002", "银行存款", "50000.00"),
            ("CREDIT", "2203", "预收账款", "50000.00"),
        ],
    )

    rows = LedgerService(db_session).get_detail(package.id, "1002")

    assert rows[0].counter_accounts == "预收账款"
    assert rows[0].counter_account_display == "预收账款 / 上海安费诺永亿通讯电子有限公司"
    assert rows[0].counter_account_name == "预收账款"
    assert rows[0].counter_auxiliary_type == "COUNTERPARTY"
    assert rows[0].counter_auxiliary_name == "上海安费诺永亿通讯电子有限公司"


def test_detail_ledger_includes_opening_balance_row(db_session):
    package = make_package(db_session)
    add_historical_balance(
        db_session,
        package,
        account_code="1002",
        account_name="银行存款",
        opening_debit="145214.66",
        closing_debit="145214.66",
    )

    rows = LedgerService(db_session).get_detail(package.id, "1002")

    assert len(rows) == 1
    assert rows[0].voucher_number == "-"
    assert rows[0].summary == "期初余额"
    assert rows[0].debit_amount == money("0.00")
    assert rows[0].credit_amount == money("0.00")
    assert rows[0].balance == money("145214.66")


def test_detail_ledger_rolls_forward_from_opening_balance(db_session):
    package = make_package(db_session)
    add_historical_balance(
        db_session,
        package,
        account_code="1002",
        account_name="银行存款",
        opening_debit="100.00",
        closing_debit="100.00",
    )
    add_voucher(
        db_session,
        package,
        number="记-0001",
        voucher_date=date(2026, 4, 2),
        status="CONFIRMED",
        entries=[
            ("DEBIT", "1002", "银行存款", "200.00"),
            ("CREDIT", "5001", "主营业务收入", "200.00"),
        ],
    )

    rows = LedgerService(db_session).get_detail(package.id, "1002")

    assert [row.summary for row in rows] == ["期初余额", "摘要记-0001"]
    assert rows[0].balance == money("100.00")
    assert rows[1].balance == money("300.00")


def test_trial_balance_returns_balanced_totals(db_session):
    package = make_package(db_session)
    add_voucher(
        db_session,
        package,
        number="记-0001",
        voucher_date=date(2026, 4, 1),
        status="CONFIRMED",
        entries=[
            ("DEBIT", "1002", "银行存款", "200.00"),
            ("CREDIT", "5001", "主营业务收入", "200.00"),
        ],
    )

    result = LedgerService(db_session).get_trial_balance(package.id)

    assert result.is_balanced is True
    assert result.period_debit_total == money("200.00")
    assert result.period_credit_total == money("200.00")
    assert result.difference == money("0.00")


def test_trial_balance_uses_historical_opening_and_auxiliary_rows(db_session):
    package = make_package(db_session)
    add_historical_balance(
        db_session,
        package,
        account_code="1122",
        account_name="应收账款",
        opening_debit="270000.00",
        closing_debit="270000.00",
    )
    add_voucher(
        db_session,
        package,
        number="记-0001",
        voucher_date=date(2026, 4, 1),
        status="CONFIRMED",
        source_data={"invoice": {"counterparty_name": "上海客户有限公司"}},
        entries=[
            ("DEBIT", "1122", "应收账款", "1000.00"),
            ("CREDIT", "5001", "主营业务收入", "1000.00"),
        ],
    )

    result = LedgerService(db_session).get_trial_balance(package.id)
    parent = next(row for row in result.rows if row.account_code == "1122" and row.row_type == "ACCOUNT")
    child = next(row for row in result.rows if row.parent_account_code == "1122" and row.row_type == "AUXILIARY")

    assert parent.opening_debit == money("270000.00")
    assert parent.period_debit == money("1000.00")
    assert parent.closing_debit == money("271000.00")
    assert parent.is_expandable is True
    assert child.auxiliary_name == "上海客户有限公司"
    assert child.account_name == "上海客户有限公司"
    assert child.period_debit == money("1000.00")
    assert child.closing_debit == money("1000.00")
