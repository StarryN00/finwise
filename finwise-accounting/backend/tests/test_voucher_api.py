import json
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.database import Base
from app.core.org_context import ensure_default_organization
from app.main import create_app
from app.models import AccountSubject, AuditLog, BankTransaction, Enterprise, Invoice, MatchRecord, MonthlyWorkPackage, Voucher


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
    assert output_row["invoice_direction_label"] == "销项发票"
    assert output_row["counterparty_role"] == "购买方"
    assert output_row["counterparty_name"] == "苏州客户有限公司"


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
