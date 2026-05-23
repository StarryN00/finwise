from datetime import date
from decimal import Decimal

from app.models import BankTransaction, Invoice
from app.services.ai_matching_service import AiMatchingUnavailableError, MoonshotAiMatchingClient, _build_ai_payload


def test_moonshot_ai_matching_client_converts_timeout_to_domain_error(monkeypatch):
    def fake_urlopen(_request, timeout):
        assert timeout == 45
        raise TimeoutError("timed out")

    monkeypatch.setattr("app.services.ai_matching_service.request.urlopen", fake_urlopen)
    client = MoonshotAiMatchingClient(api_key="test-key", base_url="https://example.test", model="kimi")

    try:
        client.propose_matches({"bank_transactions": [], "invoices": []})
    except AiMatchingUnavailableError as exc:
        assert "AI 服务响应超时" in str(exc)
    else:
        raise AssertionError("expected AiMatchingUnavailableError")


def test_ai_payload_limits_candidates_and_truncates_long_text():
    transactions = [
        BankTransaction(
            transaction_date=date(2026, 5, 1),
            summary=f"支付第{index}笔采购款 " + ("很长的摘要" * 30),
            debit_amount=Decimal("100.00"),
            credit_amount=Decimal("0.00"),
            counterparty_name=f"供应商{index}",
        )
        for index in range(1, 81)
    ]
    invoices = [
        Invoice(
            invoice_direction="INPUT",
            invoice_number=f"IN-{index}",
            invoice_date=date(2026, 5, 1),
            amount=Decimal("88.50"),
            tax_amount=Decimal("11.50"),
            total_amount=Decimal("100.00"),
            seller_name=f"供应商{index}",
            buyer_name="测试企业",
            raw_row_data={"备注": "发票备注" * 40},
        )
        for index in range(1, 81)
    ]

    payload, transaction_by_ref, invoice_by_ref = _build_ai_payload(
        transactions=transactions,
        invoices=invoices,
        enterprise_name="测试企业",
    )

    assert len(payload["bank_transactions"]) <= 32
    assert len(payload["invoices"]) <= 48
    assert len(transaction_by_ref) == len(payload["bank_transactions"])
    assert len(invoice_by_ref) == len(payload["invoices"])
    assert all(len(item["summary"]) <= 80 for item in payload["bank_transactions"])
    assert all(len(item["remark"]) <= 80 for item in payload["invoices"])
