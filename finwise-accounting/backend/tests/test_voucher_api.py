import json
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.database import Base
from app.core.org_context import ensure_default_organization
from app.main import create_app
from app.models import (
    AccountSubject,
    AuditLog,
    BankTransaction,
    Enterprise,
    Invoice,
    MatchRecord,
    MonthlyWorkPackage,
    Voucher,
    VoucherEntry,
    VoucherRule,
)


ORG = UUID("00000000-0000-0000-0000-000000000001")


def make_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    db_session = TestingSession()
    ensure_default_organization(db_session)
    app = create_app(init_db_on_startup=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=False), db_session


def make_package(db_session, *, company_name="苏州凭证接口测试有限公司"):
    enterprise = Enterprise(
        organization_id=ORG,
        name=company_name,
        unified_social_credit_code="91320500VAPI000001",
        taxpayer_type="GENERAL",
        industry="制造业",
    )
    db_session.add(enterprise)
    db_session.flush()
    package = MonthlyWorkPackage(
        organization_id=ORG,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
    )
    db_session.add(package)
    db_session.commit()
    return enterprise, package


def add_output_match(db_session, package):
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-VOUCHER-API-001",
        invoice_date=date(2026, 5, 9),
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
        seller_name="苏州凭证接口测试有限公司",
        buyer_name="苏州客户有限公司",
    )
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 10),
        summary="收到客户货款",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("1130.00"),
        counterparty_name="苏州客户有限公司",
    )
    db_session.add_all([invoice, transaction])
    db_session.flush()
    match = MatchRecord(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        bank_transaction_id=transaction.id,
        invoice_id=invoice.id,
        match_method="AUTO_EXACT",
        confidence=95,
        explanation="测试确认",
        confirmation_status="AUTO_CONFIRMED",
    )
    db_session.add(match)
    db_session.commit()
    return match


def add_output_match_with_values(
    db_session,
    package,
    *,
    invoice_number,
    invoice_date,
    transaction_date,
    buyer_name,
    total_amount,
    summary,
):
    amount = (total_amount / Decimal("1.13")).quantize(Decimal("0.01"))
    tax_amount = total_amount - amount
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        amount=amount,
        tax_amount=tax_amount,
        total_amount=total_amount,
        seller_name="苏州凭证接口测试有限公司",
        buyer_name=buyer_name,
    )
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=transaction_date,
        summary=summary,
        debit_amount=Decimal("0.00"),
        credit_amount=total_amount,
        counterparty_name=buyer_name,
    )
    db_session.add_all([invoice, transaction])
    db_session.flush()
    match = MatchRecord(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        bank_transaction_id=transaction.id,
        invoice_id=invoice.id,
        match_method="AUTO_EXACT",
        confidence=95,
        explanation="测试确认",
        confirmation_status="AUTO_CONFIRMED",
    )
    db_session.add(match)
    db_session.commit()
    return match


class StubVoucherPreprocessClient:
    def __init__(self, response=None, error=None):
        self.response = response or {"task_suggestions": []}
        self.error = error
        self.payloads = []

    def propose_voucher_tasks(self, payload):
        self.payloads.append(payload)
        if self.error:
            raise self.error
        return self.response


def test_subjects_endpoint_initializes_and_lists_subjects():
    client, db_session = make_context()
    enterprise, _package = make_package(db_session)

    response = client.post(f"/api/enterprises/{enterprise.id}/account-subjects/initialize")

    assert response.status_code == 201
    codes = {subject["code"] for subject in response.json()}
    assert "1002" in codes
    assert "560201" in codes

    list_response = client.get(f"/api/enterprises/{enterprise.id}/account-subjects")

    assert list_response.status_code == 200
    assert len(list_response.json()) >= 10


def test_generate_and_confirm_voucher_api():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")

    assert generate_response.status_code == 201
    payload = generate_response.json()
    assert payload["created_vouchers"] == 1
    voucher = payload["vouchers"][0]
    assert voucher["status"] == "PENDING_CONFIRMATION"

    confirm_response = client.post(
        f"/api/vouchers/{voucher['id']}/confirm",
        json={"confirmed_by": "operator"},
    )

    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["voucher_number"] == "记-0001"


def test_generate_vouchers_treats_bidirectional_bank_only_counterparty_as_current_account():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    counterparty = "上海涌杰实业有限公司"
    receipt = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 10),
        summary="电子汇入",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("100000.00"),
        counterparty_name=counterparty,
    )
    payment = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 27),
        summary="电子转账",
        debit_amount=Decimal("90000.00"),
        credit_amount=Decimal("0.00"),
        counterparty_name=counterparty,
    )
    db_session.add_all([receipt, payment])
    db_session.commit()

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")

    assert generate_response.status_code == 201, generate_response.text
    payload = generate_response.json()
    assert payload["created_vouchers"] == 2
    vouchers = {voucher.source_key: voucher for voucher in db_session.query(Voucher).all()}
    receipt_voucher = vouchers[f"bank:{receipt.id}"]
    payment_voucher = vouchers[f"bank:{payment.id}"]
    assert receipt_voucher.source_data["source_group_type"] == "BIDIRECTIONAL_CURRENT_ACCOUNT"
    assert payment_voucher.source_data["source_group_type"] == "BIDIRECTIONAL_CURRENT_ACCOUNT"
    assert receipt_voucher.source_data["accounting_treatment"]["treatment_type"] == "往来款暂挂"
    assert payment_voucher.source_data["accounting_treatment"]["treatment_type"] == "往来款暂挂"
    assert receipt_voucher.source_data["accounting_treatment"]["counterparty_name"] == counterparty
    assert payment_voucher.source_data["accounting_treatment"]["counterparty_name"] == counterparty
    assert "同一对方当月存在收款和付款" in receipt_voucher.ai_reason
    assert "同一对方当月存在收款和付款" in payment_voucher.ai_reason
    assert [(entry.direction, entry.account_code, entry.amount) for entry in receipt_voucher.entries] == [
        ("DEBIT", "1002", Decimal("100000.00")),
        ("CREDIT", "2241", Decimal("100000.00")),
    ]
    assert [(entry.direction, entry.account_code, entry.amount) for entry in payment_voucher.entries] == [
        ("DEBIT", "1221", Decimal("90000.00")),
        ("CREDIT", "1002", Decimal("90000.00")),
    ]


def test_list_vouchers_api_filters_confirmed_status_and_keyword():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201
    generated_voucher = generate_response.json()["vouchers"][0]
    confirm_response = client.post(
        f"/api/vouchers/{generated_voucher['id']}/confirm",
        json={"confirmed_by": "operator"},
    )
    assert confirm_response.status_code == 200

    pending = Voucher(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        voucher_date=date(2026, 5, 11),
        voucher_number=None,
        summary="待确认测试凭证",
        source_key="manual-pending",
        source_data={"counterparty_name": "不会出现在已确认列表"},
        ai_confidence=50,
        ai_reason="测试未确认",
        status="PENDING_CONFIRMATION",
    )
    pending.entries = [
        VoucherEntry(
            organization_id=ORG,
            line_no=1,
            direction="DEBIT",
            account_code="560203",
            account_name="服务费",
            amount=Decimal("10.00"),
            source_type="MANUAL",
            source_id="manual-pending",
        ),
        VoucherEntry(
            organization_id=ORG,
            line_no=2,
            direction="CREDIT",
            account_code="1002",
            account_name="银行存款",
            amount=Decimal("10.00"),
            source_type="MANUAL",
            source_id="manual-pending",
        ),
    ]
    db_session.add(pending)
    db_session.commit()

    confirmed_response = client.get(
        f"/api/monthly-packages/{package.id}/vouchers",
        params={"status": "CONFIRMED"},
    )

    assert confirmed_response.status_code == 200
    confirmed_rows = confirmed_response.json()
    assert len(confirmed_rows) == 1
    assert confirmed_rows[0]["status"] == "CONFIRMED"
    assert confirmed_rows[0]["voucher_number"] == "记-0001"

    keyword_response = client.get(
        f"/api/monthly-packages/{package.id}/vouchers",
        params={"status": "CONFIRMED", "keyword": "苏州客户"},
    )

    assert keyword_response.status_code == 200
    assert [row["voucher_number"] for row in keyword_response.json()] == ["记-0001"]

    miss_response = client.get(
        f"/api/monthly-packages/{package.id}/vouchers",
        params={"status": "CONFIRMED", "keyword": "不会出现在已确认列表"},
    )

    assert miss_response.status_code == 200
    assert miss_response.json() == []


def test_list_bank_ledger_api_returns_processing_status():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201

    response = client.get(f"/api/monthly-packages/{package.id}/bank-ledger")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["source_type"] == "BANK"
    assert row["direction_label"] == "收款/转入"
    assert row["counterparty_name"] == "苏州客户有限公司"
    assert row["transaction_amount"] == "1130.00"
    assert row["matching_status_label"] == "已匹配"
    assert row["source_processing_status"] == "PAIRED"
    assert row["source_processing_status_label"] == "已配对"
    assert row["voucher_status_label"] == "待确认"
    assert row["linked_invoice_count"] == 1
    assert row["linked_voucher_count"] == 1


def test_list_invoice_ledger_api_returns_counterparty_by_direction():
    client, db_session = make_context()
    enterprise, package = make_package(db_session)
    add_output_match(db_session, package)
    input_invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="INPUT",
        invoice_number="IN-LEDGER-001",
        invoice_date=date(2026, 5, 12),
        amount=Decimal("300.00"),
        tax_amount=Decimal("39.00"),
        total_amount=Decimal("339.00"),
        seller_name="苏州供应商有限公司",
        buyer_name=enterprise.name,
    )
    db_session.add(input_invoice)
    db_session.commit()

    response = client.get(f"/api/monthly-packages/{package.id}/invoice-ledger")

    assert response.status_code == 200
    rows = response.json()
    input_row = next(row for row in rows if row["invoice_direction"] == "INPUT")
    output_row = next(row for row in rows if row["invoice_direction"] == "OUTPUT")
    assert input_row["source_type"] == "INVOICE"
    assert input_row["invoice_direction_label"] == "进项发票"
    assert input_row["counterparty_role"] == "销售方"
    assert input_row["counterparty_name"] == "苏州供应商有限公司"
    assert input_row["matching_status_label"] == "未匹配"
    assert input_row["source_processing_status"] == "UNPROCESSED"
    assert input_row["source_processing_status_label"] == "未处理"
    assert output_row["invoice_direction_label"] == "销项发票"
    assert output_row["counterparty_role"] == "购买方"
    assert output_row["counterparty_name"] == "苏州客户有限公司"
    assert output_row["source_processing_status_label"] == "已配对"


def test_voucher_ledger_summary_api_counts_processed_sources():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)
    db_session.add(
        BankTransaction(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            transaction_date=date(2026, 5, 13),
            summary="客户预付款",
            debit_amount=Decimal("0.00"),
            credit_amount=Decimal("500.00"),
            counterparty_name="苏州预付客户有限公司",
        )
    )
    db_session.commit()

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201

    response = client.get(f"/api/monthly-packages/{package.id}/voucher-ledger-summary")

    assert response.status_code == 200
    summary = response.json()
    assert summary["bank_total_count"] == 2
    assert summary["bank_processed_count"] == 2
    assert summary["bank_pending_count"] == 0
    assert summary["invoice_total_count"] == 1
    assert summary["invoice_processed_count"] == 1
    assert summary["voucher_total_count"] == 2
    assert summary["single_source_total_amount"] == "500.00"


def test_source_ledger_rows_include_linked_voucher_ids():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201
    voucher = generate_response.json()["vouchers"][0]
    voucher_id = voucher["id"]

    bank_response = client.get(f"/api/monthly-packages/{package.id}/bank-ledger")
    invoice_response = client.get(f"/api/monthly-packages/{package.id}/invoice-ledger")

    assert bank_response.status_code == 200
    assert invoice_response.status_code == 200
    bank_link = bank_response.json()[0]["linked_vouchers"][0]
    invoice_link = invoice_response.json()[0]["linked_vouchers"][0]
    assert bank_link["id"] == voucher_id
    assert bank_link["voucher_number"] == "未编号"
    assert bank_link["status"] == "PENDING_CONFIRMATION"
    assert bank_link["status_label"] == "待确认"
    assert bank_link["summary"] == voucher["summary"]
    assert bank_link["task_type"] == "FULL_MATCH"
    assert bank_link["ai_confidence"] == voucher["ai_confidence"]
    assert invoice_link["id"] == voucher_id


def test_voucher_preprocess_endpoint_calls_kimi_client_and_records_audit(monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    _enterprise, package = make_package(db_session, company_name="昆山黛珂特电子科技有限公司")
    add_output_match(db_session, package)
    stub = StubVoucherPreprocessClient(
        response={
            "task_suggestions": [
                {
                    "source_key": "output-receipt:T001:I001",
                    "task_type": "FULL_MATCH",
                    "confidence": 96,
                    "reason": "金额一致、日期一致、方向一致",
                    "summary": "确认销售收入并收款",
                }
            ]
        }
    )
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 201
    payload = response.json()
    assert payload["ai_status"] == "SUCCESS"
    assert payload["used_kimi"] is True
    assert payload["created_vouchers"] >= 1
    assert stub.payloads
    first_payload = stub.payloads[0]
    assert "昆山黛珂特电子科技有限公司" not in json.dumps(first_payload, ensure_ascii=False)
    assert first_payload["package"]["enterprise_alias"] == "企业主体"
    assert first_payload["bank_transactions"][0]["counterparty_alias"].startswith("交易对方")

    audit = db_session.query(AuditLog).filter(AuditLog.action == "VOUCHER_AI_PREPROCESS").one()
    assert audit.after_data["ai_status"] == "SUCCESS"
    assert audit.after_data["used_kimi"] is True
    assert audit.after_data["model"]


def test_voucher_preprocess_creates_ai_match_records_before_vouchers(monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    enterprise, package = make_package(db_session)
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 20),
        summary="电子汇入",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("300.00"),
        counterparty_name="上海安费诺永亿通讯电子有限公司",
    )
    invoice1 = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="AI-MATCH-001",
        invoice_date=date(2026, 5, 18),
        amount=Decimal("100.00"),
        tax_amount=Decimal("13.00"),
        total_amount=Decimal("113.00"),
        seller_name=enterprise.name,
        buyer_name="上海安费诺永亿通讯电子有限公司",
    )
    invoice2 = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="AI-MATCH-002",
        invoice_date=date(2026, 5, 18),
        amount=Decimal("150.44"),
        tax_amount=Decimal("36.56"),
        total_amount=Decimal("187.00"),
        seller_name=enterprise.name,
        buyer_name="上海安费诺永亿通讯电子有限公司",
    )
    db_session.add_all([transaction, invoice1, invoice2])
    db_session.commit()
    stub = StubVoucherPreprocessClient(
        response={
            "analysis_summary": "已识别同一交易对方的一笔收款和两张销项发票可组合匹配。",
            "task_suggestions": [
                {
                    "source_key": "T001:I001:I002",
                    "task_type": "FULL_MATCH",
                    "confidence": 88,
                    "summary": "确认多张销售发票并收款",
                    "reason": "交易对方一致且合计金额一致",
                    "bank_refs": ["T001"],
                    "invoice_refs": ["I001", "I002"],
                }
            ],
        }
    )
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 201
    matches = db_session.query(MatchRecord).filter(MatchRecord.monthly_work_package_id == package.id).all()
    assert len(matches) == 2
    assert {match.match_method for match in matches} == {"AI_PREPROCESS"}
    assert {match.confirmation_status for match in matches} == {"AUTO_CONFIRMED"}
    assert {match.confidence for match in matches} == {88}
    assert {match.invoice_id for match in matches} == {invoice1.id, invoice2.id}
    vouchers = db_session.query(Voucher).filter(Voucher.monthly_work_package_id == package.id).all()
    assert len(vouchers) == 1
    assert vouchers[0].source_data["source_group_type"] == "ONE_BANK_TRANSACTION_MULTIPLE_INVOICES"
    assert vouchers[0].source_data["voucher_task_type"] == "FULL_MATCH"
    audit = db_session.query(AuditLog).filter(AuditLog.action == "VOUCHER_AI_PREPROCESS").one()
    assert audit.after_data["created_match_records"] == 2


def test_voucher_preprocess_does_not_create_ai_match_for_confirmed_source(monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    enterprise, package = make_package(db_session)
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 20),
        summary="电子汇入",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("300.00"),
        counterparty_name="上海安费诺永亿通讯电子有限公司",
    )
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="AI-CONFIRMED-SOURCE-001",
        invoice_date=date(2026, 5, 18),
        amount=Decimal("265.49"),
        tax_amount=Decimal("34.51"),
        total_amount=Decimal("300.00"),
        seller_name=enterprise.name,
        buyer_name="上海安费诺永亿通讯电子有限公司",
    )
    db_session.add_all([transaction, invoice])
    db_session.flush()
    confirmed_single = Voucher(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        voucher_date=transaction.transaction_date,
        voucher_number="记-9003",
        summary="已确认单边收款",
        source_key=f"bank:{transaction.id}:confirmed",
        source_data={
            "source_group_type": "BANK_ONLY",
            "voucher_task_type": "SINGLE_SOURCE",
            "bank_transaction_id": str(transaction.id),
        },
        ai_confidence=45,
        ai_reason="用户已确认该笔收款按单边处理",
        status="CONFIRMED",
        confirmed_by="operator",
    )
    confirmed_single.entries = [
        VoucherEntry(
            organization_id=ORG,
            line_no=1,
            direction="DEBIT",
            account_code="1002",
            account_name="银行存款",
            amount=Decimal("300.00"),
            source_type="BANK_TRANSACTION",
            source_id=str(transaction.id),
        ),
        VoucherEntry(
            organization_id=ORG,
            line_no=2,
            direction="CREDIT",
            account_code="2203",
            account_name="预收账款",
            amount=Decimal("300.00"),
            source_type="BANK_TRANSACTION",
            source_id=str(transaction.id),
        ),
    ]
    db_session.add(confirmed_single)
    db_session.commit()
    stub = StubVoucherPreprocessClient(
        response={
            "analysis_summary": "AI 误将已确认单边流水再次推荐匹配。",
            "task_suggestions": [
                {
                    "source_key": "T001:I001",
                    "task_type": "FULL_MATCH",
                    "confidence": 92,
                    "summary": "确认销售收入并收款",
                    "reason": "交易对方一致且金额一致",
                    "bank_refs": ["T001"],
                    "invoice_refs": ["I001"],
                }
            ],
        }
    )
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 201
    assert db_session.query(MatchRecord).filter(MatchRecord.monthly_work_package_id == package.id).count() == 0
    vouchers = db_session.query(Voucher).filter(Voucher.monthly_work_package_id == package.id).all()
    assert len(vouchers) == 2
    assert {voucher.status for voucher in vouchers} == {"CONFIRMED", "PENDING_CONFIRMATION"}
    pending = next(voucher for voucher in vouchers if voucher.status == "PENDING_CONFIRMATION")
    assert pending.source_data["source_group_type"] == "INVOICE_ONLY"
    audit = db_session.query(AuditLog).filter(AuditLog.action == "VOUCHER_AI_PREPROCESS").one()
    assert audit.after_data["created_match_records"] == 0


def test_voucher_preprocess_groups_ai_matches_with_difference_completion(monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    enterprise, package = make_package(db_session)
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 20),
        summary="电子汇入",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("350.00"),
        counterparty_name="上海安费诺永亿通讯电子有限公司",
    )
    invoice1 = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="AI-DIFF-001",
        invoice_date=date(2026, 5, 18),
        amount=Decimal("100.00"),
        tax_amount=Decimal("13.00"),
        total_amount=Decimal("113.00"),
        seller_name=enterprise.name,
        buyer_name="上海安费诺永亿通讯电子有限公司",
    )
    invoice2 = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="AI-DIFF-002",
        invoice_date=date(2026, 5, 18),
        amount=Decimal("150.44"),
        tax_amount=Decimal("36.56"),
        total_amount=Decimal("187.00"),
        seller_name=enterprise.name,
        buyer_name="上海安费诺永亿通讯电子有限公司",
    )
    db_session.add_all([transaction, invoice1, invoice2])
    db_session.commit()
    stub = StubVoucherPreprocessClient(
        response={
            "analysis_summary": "同一交易对方一笔收款可核销两张发票，差额暂挂预收账款。",
            "task_suggestions": [
                {
                    "source_key": "T001:I001:I002",
                    "task_type": "DIFFERENCE_COMPLETION",
                    "confidence": 82,
                    "summary": "确认多张销售发票并补齐收款差额",
                    "reason": "交易对方一致，收款大于发票合计，差额建议暂挂预收账款",
                    "bank_refs": ["T001"],
                    "invoice_refs": ["I001", "I002"],
                }
            ],
        }
    )
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)
    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 201
    vouchers = db_session.query(Voucher).filter(Voucher.monthly_work_package_id == package.id).all()
    pending_vouchers = [voucher for voucher in vouchers if voucher.status == "PENDING_CONFIRMATION"]
    rejected_vouchers = [voucher for voucher in vouchers if voucher.status == "REJECTED"]
    assert len(pending_vouchers) == 1
    assert len(rejected_vouchers) == 3
    assert all("SOURCE_REASSIGNED_BY_AI" in (voucher.validation_errors or []) for voucher in rejected_vouchers)
    voucher = pending_vouchers[0]
    assert voucher.source_data["source_group_type"] == "ONE_BANK_TRANSACTION_MULTIPLE_INVOICES"
    assert voucher.source_data["voucher_task_type"] == "DIFFERENCE_COMPLETION"
    assert voucher.source_data["difference_amount"] == "-50.00"
    entry_rows = {(entry.direction, entry.account_code, str(entry.amount)) for entry in voucher.entries}
    assert ("DEBIT", "1002", "350.00") in entry_rows
    assert ("CREDIT", "2203", "50.00") in entry_rows

    second_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert second_response.status_code == 201
    vouchers_after_second_run = db_session.query(Voucher).filter(Voucher.monthly_work_package_id == package.id).all()
    pending_after_second_run = [voucher for voucher in vouchers_after_second_run if voucher.status == "PENDING_CONFIRMATION"]
    assert len(pending_after_second_run) == 1
    assert pending_after_second_run[0].source_data["source_group_type"] == "ONE_BANK_TRANSACTION_MULTIPLE_INVOICES"


def test_voucher_preprocess_rejects_ai_match_when_counterparties_do_not_match(monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    enterprise, package = make_package(db_session, company_name="昆山黛珂特电子科技有限公司")
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 4, 10),
        summary="电子汇入",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("50000.00"),
        counterparty_name="上海涌杰实业有限公司",
    )
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-MISMATCH-001",
        invoice_date=date(2026, 4, 20),
        amount=Decimal("1732.01"),
        tax_amount=Decimal("225.16"),
        total_amount=Decimal("1957.17"),
        seller_name=enterprise.name,
        buyer_name="上海安费诺永亿通讯电子有限公司",
    )
    db_session.add_all([transaction, invoice])
    db_session.commit()
    stub = StubVoucherPreprocessClient(
        response={
            "analysis_summary": "错误地建议跨主体匹配。",
            "task_suggestions": [
                {
                    "task_type": "DIFFERENCE_COMPLETION",
                    "confidence": 100,
                    "summary": "确认销售收入并补齐差额",
                    "reason": "流水与发票金额完全一致，交易对方相同",
                    "bank_refs": ["T001"],
                    "invoice_refs": ["I001"],
                }
            ],
        }
    )
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 201
    assert db_session.query(MatchRecord).filter(MatchRecord.monthly_work_package_id == package.id).count() == 0
    vouchers = db_session.query(Voucher).filter(Voucher.monthly_work_package_id == package.id).all()
    assert len(vouchers) == 2
    assert {(voucher.source_data or {}).get("source_group_type") for voucher in vouchers} == {"BANK_ONLY", "INVOICE_ONLY"}
    assert all((voucher.source_data or {}).get("source_group_type") != "DIFFERENCE_COMPLETION" for voucher in vouchers)
    audit = db_session.query(AuditLog).filter(AuditLog.action == "VOUCHER_AI_PREPROCESS").one()
    assert audit.after_data["created_match_records"] == 0


def test_voucher_preprocess_does_not_recreate_operator_rejected_match(monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    enterprise, package = make_package(db_session)
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 20),
        summary="电子转账",
        debit_amount=Decimal("113.00"),
        credit_amount=Decimal("0.00"),
        counterparty_name="苏州供应商有限公司",
    )
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="INPUT",
        invoice_number="IN-REJECTED-AI-001",
        invoice_date=date(2026, 5, 18),
        amount=Decimal("100.00"),
        tax_amount=Decimal("13.00"),
        total_amount=Decimal("113.00"),
        seller_name="苏州供应商有限公司",
        buyer_name=enterprise.name,
    )
    db_session.add_all([transaction, invoice])
    db_session.flush()
    rejected_match = MatchRecord(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        bank_transaction_id=transaction.id,
        invoice_id=invoice.id,
        match_method="AUTO_EXACT",
        confidence=95,
        explanation="人工已驳回的历史匹配",
        confirmation_status="REJECTED",
    )
    db_session.add(rejected_match)
    db_session.commit()
    stub = StubVoucherPreprocessClient(
        response={
            "analysis_summary": "错误地再次建议同一组历史驳回匹配。",
            "task_suggestions": [
                {
                    "task_type": "FULL_MATCH",
                    "confidence": 96,
                    "summary": "确认费用并付款",
                    "reason": "金额一致且对方一致",
                    "bank_refs": ["T001"],
                    "invoice_refs": ["I001"],
                }
            ],
        }
    )
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 201, response.text
    matches = db_session.query(MatchRecord).filter(MatchRecord.monthly_work_package_id == package.id).all()
    assert matches == [rejected_match]
    vouchers = db_session.query(Voucher).filter(Voucher.monthly_work_package_id == package.id).all()
    assert {voucher.summary for voucher in vouchers} == {"确认费用未付款", "记录银行付款待补发票"}
    assert all(voucher.status == "PENDING_CONFIRMATION" for voucher in vouchers)
    audit = db_session.query(AuditLog).filter(AuditLog.action == "VOUCHER_AI_PREPROCESS").one()
    assert audit.after_data["created_match_records"] == 0


def test_voucher_preprocess_restores_reassigned_single_bank_voucher(monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 10),
        summary="电子汇入",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("50000.00"),
        counterparty_name="上海涌杰实业有限公司",
    )
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-UNRELATED-001",
        invoice_date=date(2026, 5, 11),
        amount=Decimal("100.00"),
        tax_amount=Decimal("13.00"),
        total_amount=Decimal("113.00"),
        seller_name="苏州凭证接口测试有限公司",
        buyer_name="无关客户有限公司",
    )
    db_session.add_all([transaction, invoice])
    db_session.flush()
    rejected_voucher = Voucher(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        voucher_date=transaction.transaction_date,
        summary="记录银行收款待补发票",
        source_key=f"bank:{transaction.id}",
        source_data={
            "source_group_type": "BANK_ONLY",
            "voucher_task_type": "SINGLE_SOURCE",
            "bank_transaction_id": str(transaction.id),
        },
        ai_confidence=45,
        ai_reason="原单边凭证被 AI 重新分配",
        status="REJECTED",
        validation_errors=["SOURCE_REASSIGNED_BY_AI"],
    )
    db_session.add(rejected_voucher)
    db_session.commit()
    stub = StubVoucherPreprocessClient(
        response={
            "analysis_summary": "暂无可配对项目。",
            "task_suggestions": [
                {
                    "task_type": "SINGLE_SOURCE",
                    "confidence": 80,
                    "summary": "单边处理",
                    "reason": "没有可配对项目",
                    "invoice_refs": ["I001"],
                }
            ],
        }
    )
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 201, response.text
    vouchers = db_session.query(Voucher).filter(Voucher.monthly_work_package_id == package.id).all()
    assert len(vouchers) == 2
    restored = next(voucher for voucher in vouchers if voucher.source_key == f"bank:{transaction.id}")
    assert restored.id == rejected_voucher.id
    assert restored.status == "PENDING_CONFIRMATION"
    assert restored.source_key == f"bank:{transaction.id}"
    assert restored.validation_errors == []
    assert restored.summary == "记录银行收款待补发票"
    assert [(entry.direction, entry.account_code, entry.amount) for entry in restored.entries] == [
        ("DEBIT", "1002", Decimal("50000.00")),
        ("CREDIT", "2203", Decimal("50000.00")),
    ]
    audit = db_session.query(AuditLog).filter(AuditLog.action == "VOUCHER_AI_PREPROCESS").one()
    assert audit.after_data["created_vouchers"] == 2


def test_voucher_preprocess_uses_kimi_k26_supported_temperature():
    from app.services import voucher_ai_preprocess_service as service

    assert service._temperature_for_model("kimi-k2.6") == 1
    assert service._temperature_for_model(" moonshot-v1-32k ") == 0.2


def test_voucher_preprocess_endpoint_interrupts_when_kimi_fails(monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)
    stub = StubVoucherPreprocessClient(error=service.VoucherAiPreprocessUnavailableError("timeout"))
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 503
    payload = response.json()
    assert "AI 预处理失败" in payload["detail"]
    assert db_session.query(Voucher).count() == 0
    audit = db_session.query(AuditLog).filter(AuditLog.action == "VOUCHER_AI_PREPROCESS").one()
    assert audit.after_data["ai_status"] == "FAILED"
    assert audit.after_data["created_vouchers"] == 0


def test_voucher_preprocess_payload_redacts_raw_summary_and_rule_keywords(monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    enterprise, package = make_package(db_session, company_name="昆山黛珂特电子科技有限公司")
    enterprise.industry = "制造业 昆山敏感企业有限公司 91320500INDUSTRY000001"
    db_session.add(
        BankTransaction(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            transaction_date=date(2026, 5, 10),
            summary=(
                "电子转账 昆山黛珂特电子科技有限公司 收到上海敏感客户有限公司 账号6222020202020202020 "
                "发票32002605090012345678 税号91320500REDACT000001 货款"
            ),
            debit_amount=Decimal("0.00"),
            credit_amount=Decimal("1130.00"),
            counterparty_name="上海敏感客户有限公司",
        )
    )
    db_session.add(
        Invoice(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            invoice_direction="OUTPUT",
            invoice_number="32002605090012345678",
            invoice_date=date(2026, 5, 9),
            amount=Decimal("1000.00"),
            tax_amount=Decimal("130.00"),
            total_amount=Decimal("1130.00"),
            seller_name=enterprise.name,
            buyer_name="上海敏感客户有限公司",
        )
    )
    db_session.add(
        VoucherRule(
            organization_id=ORG,
            enterprise_id=enterprise.id,
            rule_name="上海敏感客户有限公司 专属销售收款规则",
            summary_keywords=["昆山黛珂特电子科技有限公司", "账号6222020202020202020", "发票32002605090012345678", "货款"],
            counterparty_pattern="上海敏感客户有限公司",
            source_direction="RECEIPT",
            invoice_direction="OUTPUT",
            summary_template="确认销售收款",
            debit_account_code="1002",
            credit_account_code="6001",
        )
    )
    db_session.commit()
    stub = StubVoucherPreprocessClient(response={"task_suggestions": [{"task_type": "SINGLE_SOURCE", "confidence": 80}]})
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 201
    payload_text = json.dumps(stub.payloads[0], ensure_ascii=False)
    for raw_secret in [
        "昆山黛珂特电子科技有限公司",
        "上海敏感客户有限公司",
        "昆山敏感企业有限公司",
        "91320500INDUSTRY000001",
        "6222020202020202020",
        "32002605090012345678",
        "91320500REDACT000001",
        "账号6222020202020202020",
    ]:
        assert raw_secret not in payload_text
    assert stub.payloads[0]["historical_rules"][0]["rule_alias"] == "R001"
    assert "电子转账" in payload_text
    assert "货款" in payload_text


@pytest.mark.parametrize(
    "ai_response",
    [
        {},
        {"task_suggestions": []},
        {"task_suggestions": "FULL_MATCH"},
        {"task_suggestions": [{"task_type": "FULL_MATCH", "confidence": 101}]},
        {"task_suggestions": [{"task_type": "BAD_TASK", "confidence": 80}]},
    ],
)
def test_voucher_preprocess_endpoint_interrupts_on_invalid_kimi_output(monkeypatch, ai_response):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)
    stub = StubVoucherPreprocessClient(response=ai_response)
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 503
    assert db_session.query(Voucher).count() == 0
    audit = db_session.query(AuditLog).filter(AuditLog.action == "VOUCHER_AI_PREPROCESS").one()
    assert audit.after_data["ai_status"] == "FAILED"
    assert audit.after_data["used_kimi"] is True
    assert audit.after_data["created_vouchers"] == 0


def test_voucher_preprocess_missing_api_key_records_no_kimi_call(monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)
    monkeypatch.setattr(
        service,
        "create_default_voucher_preprocess_client",
        lambda: service.MoonshotVoucherPreprocessClient(api_key="", base_url="https://api.moonshot.cn/v1", model="kimi-test"),
    )

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 503
    assert db_session.query(Voucher).count() == 0
    audit = db_session.query(AuditLog).filter(AuditLog.action == "VOUCHER_AI_PREPROCESS").one()
    assert audit.after_data["ai_status"] == "FAILED"
    assert audit.after_data["used_kimi"] is False
    assert audit.after_data["created_vouchers"] == 0


def test_voucher_preprocess_endpoint_interrupts_on_unknown_kimi_refs(monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)
    stub = StubVoucherPreprocessClient(
        response={
            "task_suggestions": [
                {
                    "task_type": "FULL_MATCH",
                    "confidence": 90,
                    "reason": "引用不存在的发票",
                    "bank_refs": ["T001"],
                    "invoice_refs": ["I999"],
                }
            ]
        }
    )
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 503
    assert db_session.query(Voucher).count() == 0
    audit = db_session.query(AuditLog).filter(AuditLog.action == "VOUCHER_AI_PREPROCESS").one()
    assert audit.after_data["ai_status"] == "FAILED"
    assert audit.after_data["created_vouchers"] == 0


def test_voucher_preprocess_cleans_created_vouchers_when_post_generation_fails(monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)
    stub = StubVoucherPreprocessClient(response={"task_suggestions": [{"task_type": "FULL_MATCH", "confidence": 90}]})
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)

    def fail_metadata(*args, **kwargs):
        raise RuntimeError("metadata persistence failed for 昆山敏感企业有限公司 91320500SECRET000001")

    monkeypatch.setattr(service, "_attach_preprocess_metadata", fail_metadata)

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 503
    assert db_session.query(Voucher).count() == 0
    audit = db_session.query(AuditLog).filter(AuditLog.action == "VOUCHER_AI_PREPROCESS").one()
    assert audit.after_data["ai_status"] == "FAILED"
    assert audit.after_data["created_vouchers"] == 0
    assert audit.after_data["error_summary"] == "POST_GENERATION_PERSISTENCE_FAILED"
    response_text = json.dumps(response.json(), ensure_ascii=False)
    audit_text = json.dumps(audit.after_data, ensure_ascii=False)
    for raw_secret in ["昆山敏感企业有限公司", "91320500SECRET000001", "metadata persistence failed"]:
        assert raw_secret not in response_text
        assert raw_secret not in audit_text


def test_voucher_preprocess_matches_full_match_suggestions_by_source_refs(monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match_with_values(
        db_session,
        package,
        invoice_number="OUT-KIMI-001",
        invoice_date=date(2026, 5, 8),
        transaction_date=date(2026, 5, 9),
        buyer_name="苏州第一客户有限公司",
        total_amount=Decimal("1130.00"),
        summary="收到第一客户货款",
    )
    add_output_match_with_values(
        db_session,
        package,
        invoice_number="OUT-KIMI-002",
        invoice_date=date(2026, 5, 10),
        transaction_date=date(2026, 5, 11),
        buyer_name="苏州第二客户有限公司",
        total_amount=Decimal("2260.00"),
        summary="收到第二客户货款",
    )
    stub = StubVoucherPreprocessClient(
        response={
            "task_suggestions": [
                {
                    "task_type": "FULL_MATCH",
                    "confidence": 91,
                    "reason": "第一笔匹配理由",
                    "bank_refs": ["T001"],
                    "invoice_refs": ["I001"],
                },
                {
                    "task_type": "FULL_MATCH",
                    "confidence": 97,
                    "reason": "第二笔匹配理由",
                    "bank_refs": ["T002"],
                    "invoice_refs": ["I002"],
                },
            ]
        }
    )
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 201
    vouchers = db_session.query(Voucher).order_by(Voucher.voucher_date).all()
    assert [voucher.ai_reason for voucher in vouchers] == ["第一笔匹配理由", "第二笔匹配理由"]
    assert [voucher.ai_confidence for voucher in vouchers] == [91, 97]


def test_reject_voucher_api_marks_voucher_as_rejected_without_number():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201
    voucher_id = generate_response.json()["vouchers"][0]["id"]

    reject_response = client.post(
        f"/api/vouchers/{voucher_id}/reject",
        json={"rejected_by": "operator", "reason": "匹配对象不正确"},
    )

    assert reject_response.status_code == 200
    rejected = reject_response.json()
    assert rejected["status"] == "REJECTED"
    assert rejected["voucher_number"] is None
    assert rejected["confirmed_by"] == "operator"
    assert "OPERATOR_REJECTED" in rejected["validation_errors"]


def test_reopen_confirmed_voucher_api_restores_pending_editable_state():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201
    voucher_id = generate_response.json()["vouchers"][0]["id"]

    confirm_response = client.post(
        f"/api/vouchers/{voucher_id}/confirm",
        json={"confirmed_by": "operator"},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "CONFIRMED"
    assert confirm_response.json()["voucher_number"] == "记-0001"

    reopen_response = client.post(
        f"/api/vouchers/{voucher_id}/reopen",
        json={"reopened_by": "operator", "reason": "需要重新核对匹配来源"},
    )

    assert reopen_response.status_code == 200
    reopened = reopen_response.json()
    assert reopened["status"] == "PENDING_CONFIRMATION"
    assert reopened["voucher_number"] is None
    assert reopened["confirmed_by"] is None
    assert reopened["confirmed_at"] is None
    assert reopened["validation_errors"] == []


def test_reopen_rejected_voucher_api_clears_operator_rejected_error():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201
    voucher_id = generate_response.json()["vouchers"][0]["id"]

    reject_response = client.post(
        f"/api/vouchers/{voucher_id}/reject",
        json={"rejected_by": "operator", "reason": "匹配对象不正确"},
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "REJECTED"
    assert "OPERATOR_REJECTED" in reject_response.json()["validation_errors"]

    reopen_response = client.post(
        f"/api/vouchers/{voucher_id}/reopen",
        json={"reopened_by": "operator", "reason": "重新选择匹配对象"},
    )

    assert reopen_response.status_code == 200
    reopened = reopen_response.json()
    assert reopened["status"] == "PENDING_CONFIRMATION"
    assert reopened["voucher_number"] is None
    assert reopened["confirmed_by"] is None
    assert reopened["confirmed_at"] is None
    assert "OPERATOR_REJECTED" not in reopened["validation_errors"]


def test_rematch_voucher_api_lists_candidates_and_rebuilds_draft():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    current_match = add_output_match(db_session, package)
    used_invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-VOUCHER-API-USED",
        invoice_date=date(2026, 5, 11),
        amount=Decimal("2000.00"),
        tax_amount=Decimal("260.00"),
        total_amount=Decimal("2260.00"),
        seller_name="苏州凭证接口测试有限公司",
        buyer_name="苏州已占用客户有限公司",
    )
    used_transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 11),
        summary="收到已占用客户货款",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("2260.00"),
        counterparty_name="苏州已占用客户有限公司",
    )
    db_session.add_all([used_invoice, used_transaction])
    db_session.flush()
    used_match = MatchRecord(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        bank_transaction_id=used_transaction.id,
        invoice_id=used_invoice.id,
        match_method="AUTO_EXACT",
        confidence=95,
        explanation="已占用测试",
        confirmation_status="AUTO_CONFIRMED",
    )
    db_session.add(used_match)
    replacement_invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-VOUCHER-API-REMAP",
        invoice_date=date(2026, 5, 10),
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
        seller_name="苏州凭证接口测试有限公司",
        buyer_name="苏州客户有限公司",
    )
    db_session.add(replacement_invoice)
    db_session.commit()

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201
    generated = sorted(generate_response.json()["vouchers"], key=lambda item: item["voucher_date"])
    voucher_id = next(item["id"] for item in generated if item["source_key"] == f"match:{current_match.id}")
    used_voucher_id = next(item["id"] for item in generated if item["source_key"] == f"match:{used_match.id}")
    confirm_response = client.post(
        f"/api/vouchers/{used_voucher_id}/confirm",
        json={"confirmed_by": "operator"},
    )
    assert confirm_response.status_code == 200

    candidates_response = client.get(f"/api/vouchers/{voucher_id}/rematch-candidates")

    assert candidates_response.status_code == 200
    candidates = candidates_response.json()
    assert candidates["current_invoice_id"] != str(replacement_invoice.id)
    invoice_candidates = {item["id"]: item for item in candidates["invoice_candidates"]}
    bank_candidates = {item["id"]: item for item in candidates["bank_candidates"]}
    assert invoice_candidates[str(current_match.invoice_id)]["is_current"] is True
    assert invoice_candidates[str(current_match.invoice_id)]["is_selectable"] is False
    assert invoice_candidates[str(current_match.invoice_id)]["disabled_reason"] == "当前凭证正在使用"
    assert invoice_candidates[str(current_match.invoice_id)]["direction_label"] == "销项发票"
    assert invoice_candidates[str(current_match.invoice_id)]["counterparty_role"] == "购买方"
    assert invoice_candidates[str(current_match.invoice_id)]["detail"]["invoice_direction"] == "销项发票"
    assert invoice_candidates[str(current_match.invoice_id)]["detail"]["invoice_number"] == "OUT-VOUCHER-API-001"
    assert invoice_candidates[str(current_match.invoice_id)]["detail"]["seller_name"] == "苏州凭证接口测试有限公司"
    assert invoice_candidates[str(current_match.invoice_id)]["detail"]["buyer_name"] == "苏州客户有限公司"
    assert invoice_candidates[str(used_invoice.id)]["is_used"] is True
    assert invoice_candidates[str(used_invoice.id)]["used_by_status"] == "CONFIRMED"
    assert invoice_candidates[str(used_invoice.id)]["is_selectable"] is False
    assert invoice_candidates[str(used_invoice.id)]["disabled_reason"] == "已被已确认凭证使用"
    assert bank_candidates[str(used_transaction.id)]["is_used"] is True
    assert bank_candidates[str(used_transaction.id)]["is_selectable"] is False
    assert bank_candidates[str(used_transaction.id)]["direction_label"] == "收款/转入"
    assert bank_candidates[str(used_transaction.id)]["counterparty_role"] == "交易对方"
    assert bank_candidates[str(used_transaction.id)]["detail"]["summary"] == "收到已占用客户货款"
    assert bank_candidates[str(used_transaction.id)]["detail"]["credit_amount"] == "2260.00"
    assert invoice_candidates[str(replacement_invoice.id)]["is_selectable"] is True

    rematch_response = client.post(
        f"/api/vouchers/{voucher_id}/rematch",
        json={"invoice_id": str(replacement_invoice.id)},
    )

    assert rematch_response.status_code == 200
    rematched = rematch_response.json()
    assert rematched["id"] == voucher_id
    assert rematched["status"] == "PENDING_CONFIRMATION"
    assert rematched["voucher_number"] is None
    assert rematched["source_data"]["invoice_id"] == str(replacement_invoice.id)
    assert rematched["source_data"]["invoice"]["invoice_number"] == "OUT-VOUCHER-API-REMAP"
    assert rematched["source_data"]["match"]["match_method"] == "MANUAL_REMAP"
    assert rematched["validation_errors"] == []


def test_rematch_voucher_api_can_replace_both_bank_and_invoice_sources():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)
    replacement_invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="INPUT",
        invoice_number="IN-VOUCHER-API-BOTH",
        invoice_date=date(2026, 5, 14),
        amount=Decimal("500.00"),
        tax_amount=Decimal("65.00"),
        total_amount=Decimal("565.00"),
        seller_name="无锡材料供应商有限公司",
        buyer_name="苏州凭证接口测试有限公司",
    )
    replacement_transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 15),
        summary="支付材料款",
        debit_amount=Decimal("565.00"),
        credit_amount=Decimal("0.00"),
        counterparty_name="无锡材料供应商有限公司",
        balance=Decimal("12345.67"),
    )
    db_session.add_all([replacement_invoice, replacement_transaction])
    db_session.commit()

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201
    voucher_id = generate_response.json()["vouchers"][0]["id"]

    rematch_response = client.post(
        f"/api/vouchers/{voucher_id}/rematch",
        json={
            "bank_transaction_id": str(replacement_transaction.id),
            "invoice_id": str(replacement_invoice.id),
        },
    )

    assert rematch_response.status_code == 200
    rematched = rematch_response.json()
    assert rematched["status"] == "PENDING_CONFIRMATION"
    assert rematched["summary"] == "确认费用并付款"
    assert rematched["source_data"]["bank_transaction_id"] == str(replacement_transaction.id)
    assert rematched["source_data"]["invoice_id"] == str(replacement_invoice.id)
    assert rematched["source_data"]["bank_transaction"]["direction_label"] == "付款/转出"
    assert rematched["source_data"]["invoice"]["counterparty_name"] == "无锡材料供应商有限公司"
    assert rematched["source_data"]["invoice"]["counterparty_role"] == "销售方"
    assert rematched["source_data"]["match"]["match_method"] == "MANUAL_REMAP"


def test_rematch_voucher_api_can_match_one_invoice_to_multiple_bank_transactions():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    current_match = add_output_match(db_session, package)
    replacement_invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="INPUT",
        invoice_number="IN-VOUCHER-API-MULTI-BANK",
        invoice_date=date(2026, 5, 18),
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
        seller_name="昆山分批付款供应商有限公司",
        buyer_name="苏州凭证接口测试有限公司",
    )
    first_transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 19),
        summary="支付首笔材料款",
        debit_amount=Decimal("600.00"),
        credit_amount=Decimal("0.00"),
        counterparty_name="昆山分批付款供应商有限公司",
    )
    second_transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 20),
        summary="支付尾款",
        debit_amount=Decimal("530.00"),
        credit_amount=Decimal("0.00"),
        counterparty_name="昆山分批付款供应商有限公司",
    )
    db_session.add_all([replacement_invoice, first_transaction, second_transaction])
    db_session.commit()

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201
    voucher_id = next(
        item["id"] for item in generate_response.json()["vouchers"] if item["source_key"] == f"match:{current_match.id}"
    )

    rematch_response = client.post(
        f"/api/vouchers/{voucher_id}/rematch",
        json={
            "invoice_ids": [str(replacement_invoice.id)],
            "bank_transaction_ids": [str(first_transaction.id), str(second_transaction.id)],
        },
    )

    assert rematch_response.status_code == 200
    rematched = rematch_response.json()
    assert rematched["summary"] == "确认费用并分次付款"
    assert rematched["source_data"]["source_group_type"] == "ONE_INVOICE_MULTIPLE_BANK_TRANSACTIONS"
    assert rematched["source_data"]["invoice_ids"] == [str(replacement_invoice.id)]
    assert set(rematched["source_data"]["bank_transaction_ids"]) == {
        str(first_transaction.id),
        str(second_transaction.id),
    }
    assert [entry["account_code"] for entry in rematched["entries"]] == ["560203", "22210101", "1002"]
    assert rematched["validation_errors"] == []


def test_rematch_voucher_api_can_match_one_bank_transaction_to_multiple_invoices():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    current_match = add_output_match(db_session, package)
    replacement_transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 21),
        summary="收到客户合并付款",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("1695.00"),
        counterparty_name="苏州合并付款客户有限公司",
    )
    first_invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-VOUCHER-API-MULTI-001",
        invoice_date=date(2026, 5, 20),
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
        seller_name="苏州凭证接口测试有限公司",
        buyer_name="苏州合并付款客户有限公司",
    )
    second_invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-VOUCHER-API-MULTI-002",
        invoice_date=date(2026, 5, 20),
        amount=Decimal("500.00"),
        tax_amount=Decimal("65.00"),
        total_amount=Decimal("565.00"),
        seller_name="苏州凭证接口测试有限公司",
        buyer_name="苏州合并付款客户有限公司",
    )
    db_session.add_all([replacement_transaction, first_invoice, second_invoice])
    db_session.commit()

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201
    voucher_id = next(
        item["id"] for item in generate_response.json()["vouchers"] if item["source_key"] == f"match:{current_match.id}"
    )

    rematch_response = client.post(
        f"/api/vouchers/{voucher_id}/rematch",
        json={
            "bank_transaction_ids": [str(replacement_transaction.id)],
            "invoice_ids": [str(first_invoice.id), str(second_invoice.id)],
        },
    )

    assert rematch_response.status_code == 200
    rematched = rematch_response.json()
    assert rematched["summary"] == "确认多张销售发票并收款"
    assert rematched["source_data"]["source_group_type"] == "ONE_BANK_TRANSACTION_MULTIPLE_INVOICES"
    assert rematched["source_data"]["bank_transaction_ids"] == [str(replacement_transaction.id)]
    assert set(rematched["source_data"]["invoice_ids"]) == {str(first_invoice.id), str(second_invoice.id)}
    assert [entry["account_code"] for entry in rematched["entries"]] == ["1002", "5001", "22210102"]
    assert rematched["validation_errors"] == []


def test_adjust_single_bank_receipt_voucher_treatment_api_rebuilds_entries_and_records_reason():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 22),
        summary="收到临时往来款",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("3000.00"),
        counterparty_name="苏州往来客户有限公司",
    )
    db_session.add(transaction)
    db_session.commit()

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201
    voucher = generate_response.json()["vouchers"][0]
    assert voucher["summary"] == "记录银行收款待补发票"
    assert [entry["account_code"] for entry in voucher["entries"]] == ["1002", "2203"]

    adjust_response = client.post(
        f"/api/vouchers/{voucher['id']}/treatment-adjustment",
        json={
            "treatment_type": "往来款暂挂",
            "summary": "收到客户临时往来款",
            "debit_account_code": "1002",
            "credit_account_code": "2241",
            "note": "客户说明该笔为临时往来款，暂不确认收入",
        },
    )

    assert adjust_response.status_code == 200
    adjusted = adjust_response.json()
    assert adjusted["status"] == "PENDING_CONFIRMATION"
    assert adjusted["summary"] == "收到客户临时往来款"
    assert [entry["account_code"] for entry in adjusted["entries"]] == ["1002", "2241"]
    assert adjusted["source_data"]["accounting_treatment"]["treatment_type"] == "往来款暂挂"
    assert adjusted["source_data"]["accounting_treatment"]["note"] == "客户说明该笔为临时往来款，暂不确认收入"
    assert adjusted["validation_errors"] == []


def test_voucher_merge_suggestions_api_lists_and_applies_pending_bank_group():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    transactions = [
        BankTransaction(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            transaction_date=date(2026, 5, day),
            summary="电子转账",
            debit_amount=amount,
            credit_amount=Decimal("0.00"),
            counterparty_name="昆山合并付款供应商有限公司",
        )
        for day, amount in (
            (8, Decimal("120.00")),
            (15, Decimal("180.00")),
            (22, Decimal("300.00")),
        )
    ]
    db_session.add_all(transactions)
    db_session.commit()

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201, generate_response.text
    assert generate_response.json()["created_vouchers"] == 3

    suggestions_response = client.get(f"/api/monthly-packages/{package.id}/vouchers/merge-suggestions")
    assert suggestions_response.status_code == 200, suggestions_response.text
    suggestions = suggestions_response.json()["suggestions"]
    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion["counterparty_name"] == "昆山合并付款供应商有限公司"
    assert suggestion["direction"] == "OUTFLOW"
    assert Decimal(str(suggestion["total_amount"])) == Decimal("600.00")
    assert len(suggestion["source_voucher_ids"]) == 3
    assert len(suggestion["sources"]) == 3
    assert suggestion["recommended_credit_account_code"] == "1002"

    apply_response = client.post(
        f"/api/monthly-packages/{package.id}/vouchers/merge-suggestions/apply",
        json={"source_voucher_ids": suggestion["source_voucher_ids"], "applied_by": "api-test"},
    )

    assert apply_response.status_code == 200, apply_response.text
    merged = apply_response.json()
    assert merged["status"] == "PENDING_CONFIRMATION"
    assert merged["source_data"]["source_group_type"] == "AI_SUGGESTED_BANK_MERGE"
    assert merged["source_data"]["voucher_task_type"] == "AI_SUGGESTED_MERGE"
    assert len(merged["source_data"]["bank_transaction_ids"]) == 3
    assert [entry["account_code"] for entry in merged["entries"]] == ["1123", "1002"]
    assert Decimal(str(merged["entries"][0]["amount"])) == Decimal("600.00")

    db_session.expire_all()
    source_vouchers = (
        db_session.query(Voucher)
        .filter(Voucher.id.in_([UUID(item) for item in suggestion["source_voucher_ids"]]))
        .all()
    )
    assert {voucher.status for voucher in source_vouchers} == {"REJECTED"}
    assert all("MERGED_BY_OPERATOR" in (voucher.validation_errors or []) for voucher in source_vouchers)


def test_confirm_voucher_api_validation_failure_returns_400_and_keeps_pending_status():
    client, db_session = make_context()
    _enterprise, package = make_package(db_session)
    add_output_match(db_session, package)

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201
    voucher_id = generate_response.json()["vouchers"][0]["id"]

    bank_subject = (
        db_session.query(AccountSubject)
        .filter(AccountSubject.enterprise_id == package.enterprise_id, AccountSubject.code == "1002")
        .one()
    )
    bank_subject.is_enabled = False
    db_session.commit()

    confirm_response = client.post(
        f"/api/vouchers/{voucher_id}/confirm",
        json={"confirmed_by": "operator"},
    )

    assert confirm_response.status_code == 400
    assert "SUBJECT_NOT_ENABLED" in confirm_response.json()["detail"]

    db_session.expire_all()
    voucher = db_session.get(Voucher, UUID(voucher_id))
    assert voucher.status == "PENDING_CONFIRMATION"
    assert voucher.voucher_number is None
    assert voucher.confirmed_by is None
    assert voucher.confirmed_at is None
