from datetime import date
from decimal import Decimal
from json import dumps
from uuid import UUID

from app.models import BankTransaction, Enterprise, Invoice, MatchRecord, MonthlyWorkPackage
from app.services.ai_matching_service import run_ai_matching


ORG = UUID("00000000-0000-0000-0000-000000000001")


class FakeAiMatchingClient:
    def __init__(self):
        self.payloads = []

    def propose_matches(self, payload):
        self.payloads.append(payload)
        high_transaction_ref = next(row["ref"] for row in payload["bank_transactions"] if row["amount"] == "1130.00")
        high_invoice_ref = next(row["ref"] for row in payload["invoices"] if row["amount"] == "1130.00")
        low_transaction_ref = next(row["ref"] for row in payload["bank_transactions"] if row["amount"] == "2260.00")
        low_invoice_ref = next(row["ref"] for row in payload["invoices"] if row["amount"] == "2260.00")
        return {
            "matches": [
                {
                    "transaction_ref": high_transaction_ref,
                    "invoice_ref": high_invoice_ref,
                    "confidence": 92,
                    "explanation": "金额一致，日期接近，往来主体一致",
                },
                {
                    "transaction_ref": low_transaction_ref,
                    "invoice_ref": low_invoice_ref,
                    "confidence": 72,
                    "explanation": "金额接近但主体不确定",
                },
            ]
        }


def make_package(db_session):
    enterprise = Enterprise(
        organization_id=ORG,
        name="昆山真实企业有限公司",
        unified_social_credit_code="91320500AI0000001",
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


def add_transaction(db_session, package, *, summary, amount, counterparty):
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 8),
        summary=summary,
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal(amount),
        counterparty_name=counterparty,
    )
    db_session.add(transaction)
    db_session.flush()
    return transaction


def add_invoice(db_session, package, *, number, total_amount, buyer):
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number=number,
        invoice_date=date(2026, 5, 9),
        amount=Decimal(total_amount) - Decimal("130.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal(total_amount),
        seller_name="昆山真实企业有限公司",
        buyer_name=buyer,
        raw_row_data={"备注": "昆山真实企业有限公司向苏州客户有限公司开票"},
    )
    db_session.add(invoice)
    db_session.flush()
    return invoice


def test_run_ai_matching_creates_pending_matches_from_desensitized_payload(db_session):
    _enterprise, package = make_package(db_session)
    high_transaction = add_transaction(
        db_session,
        package,
        summary="收到苏州客户有限公司货款",
        amount="1130.00",
        counterparty="苏州客户有限公司",
    )
    low_transaction = add_transaction(
        db_session,
        package,
        summary="收到上海客户有限公司货款",
        amount="2260.00",
        counterparty="上海客户有限公司",
    )
    high_invoice = add_invoice(db_session, package, number="OUT-AI-001", total_amount="1130.00", buyer="苏州客户有限公司")
    add_invoice(db_session, package, number="OUT-AI-002", total_amount="2260.00", buyer="上海客户有限公司")
    db_session.commit()
    client = FakeAiMatchingClient()

    result = run_ai_matching(db_session, monthly_work_package_id=package.id, ai_client=client)

    assert result["created_matches"] == 1
    assert result["uncertain_matches"] == 1
    match = db_session.query(MatchRecord).one()
    assert match.bank_transaction_id == high_transaction.id
    assert match.invoice_id == high_invoice.id
    assert match.confirmation_status == "PENDING"
    assert match.match_method == "AI_SUGGESTED"
    assert match.confidence == 92

    payload_text = dumps(client.payloads[0], ensure_ascii=False)
    assert "昆山真实企业有限公司" not in payload_text
    assert "苏州客户有限公司" not in payload_text
    assert "上海客户有限公司" not in payload_text
    assert "91320500AI0000001" not in payload_text
    assert client.payloads[0]["bank_transactions"][0]["ref"] == "T001"
    assert client.payloads[0]["invoices"][0]["ref"] == "I001"
