# Voucher Ledger AI Preprocessing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the voucher workbench’s standalone draft list with bank-ledger and invoice-ledger working views, and make the “AI 预处理” button verifiably call Kimi to compare both sides and produce voucher treatment suggestions.

**Architecture:** Backend keeps the existing voucher draft model and ledger APIs, adds source-row voucher links plus a Kimi preprocessing orchestration layer with audit logs and explicit fallback status. Frontend refactors the source ledgers into reusable components, embeds them in `VoucherWorkbenchView`, and routes row clicks into the existing right-side voucher review panel. The old generate endpoint remains compatible, but the primary frontend action becomes `/vouchers/preprocess`.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, pytest, Vue 3, Element Plus, Pinia, Vitest, Playwright/browser verification.

---

## File Structure

- Modify `finwise-accounting/backend/app/schemas/voucher.py`
  - Add `VoucherLedgerLinkRead`, `VoucherPreprocessResponse`, `VoucherPreprocessAuditRead`.
  - Extend `BankLedgerRowRead` and `InvoiceLedgerRowRead` with `linked_vouchers`.

- Modify `finwise-accounting/backend/app/services/voucher_service.py`
  - Reuse existing source link indexes to expose voucher IDs, numbers, statuses, summaries and task types on ledger rows.
  - Keep `generate_voucher_drafts()` as local deterministic/fallback generator.

- Create `finwise-accounting/backend/app/services/voucher_ai_preprocess_service.py`
  - Build desensitized Kimi payload from bank transactions, invoices, matched records, historical rules, and package context.
  - Call Moonshot/Kimi API with JSON response format.
  - Persist an `AuditLog` entry with action `VOUCHER_AI_PREPROCESS`.
  - Run local voucher draft generation after Kimi returns or after fallback.
  - Attach AI preprocessing metadata to generated vouchers where source keys can be matched.

- Modify `finwise-accounting/backend/app/api/vouchers.py`
  - Add `POST /api/monthly-packages/{package_id}/vouchers/preprocess`.
  - Keep `POST /api/monthly-packages/{package_id}/vouchers/generate` for compatibility.

- Modify `finwise-accounting/frontend/src/api/client.js`
  - Add `api.vouchers.preprocess(packageId)` with `AI_REQUEST_TIMEOUT_MS`.

- Create `finwise-accounting/frontend/src/components/source-ledgers/BankLedgerTable.vue`
  - Reusable bank-ledger table for standalone page and voucher workbench.

- Create `finwise-accounting/frontend/src/components/source-ledgers/InvoiceLedgerTable.vue`
  - Reusable invoice-ledger table for standalone page and voucher workbench.

- Create `finwise-accounting/frontend/src/components/source-ledgers/ledgerFormatters.js`
  - Shared amount, status tag, keyword filter and voucher link label formatters.

- Modify `finwise-accounting/frontend/src/views/BankLedgerView.vue`
  - Use `BankLedgerTable`.

- Modify `finwise-accounting/frontend/src/views/InvoiceLedgerView.vue`
  - Use `InvoiceLedgerTable`.

- Modify `finwise-accounting/frontend/src/views/VoucherWorkbenchView.vue`
  - Rename button to `AI 预处理`.
  - Replace the left “待处理凭证列表” with two tabs: `按资金流水整理` and `按发票台账整理`.
  - Load bank ledger, invoice ledger, voucher list, and summary together.
  - Clicking a ledger row selects its linked voucher or the best related voucher.
  - Display Kimi/fallback status message from preprocessing response.

- Modify tests:
  - `finwise-accounting/backend/tests/test_voucher_api.py`
  - `finwise-accounting/backend/tests/test_voucher_service.py`
  - `finwise-accounting/frontend/src/views/VoucherWorkbenchView.spec.js`
  - `finwise-accounting/frontend/src/views/SourceLedgerView.spec.js`
  - `finwise-accounting/frontend/src/api/client.spec.js`

---

### Task 1: Backend Ledger Rows Expose Linked Voucher IDs

**Files:**
- Modify: `finwise-accounting/backend/app/schemas/voucher.py`
- Modify: `finwise-accounting/backend/app/services/voucher_service.py`
- Test: `finwise-accounting/backend/tests/test_voucher_api.py`

- [ ] **Step 1: Write the failing API test**

Add this test to `finwise-accounting/backend/tests/test_voucher_api.py` near `test_voucher_ledger_summary_api_counts_processed_sources`:

```python
def test_source_ledger_rows_include_linked_voucher_ids(db_session):
    enterprise, package = create_enterprise_with_package(db_session)
    bank = create_bank_transaction(
        db_session,
        package,
        transaction_date=date(2026, 4, 8),
        summary="收到客户货款",
        counterparty_name="客户A",
        debit_amount=Decimal("0"),
        credit_amount=Decimal("1130.00"),
    )
    invoice = create_invoice(
        db_session,
        package,
        invoice_direction="OUTPUT",
        invoice_date=date(2026, 4, 8),
        buyer_name="客户A",
        seller_name=enterprise.name,
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
    )
    db_session.add(
        MatchRecord(
            organization_id=package.organization_id,
            monthly_work_package_id=package.id,
            bank_transaction_id=bank.id,
            invoice_id=invoice.id,
            match_method="AUTO_EXACT",
            confidence=95,
            confirmation_status="CONFIRMED",
            explanation="金额一致且日期相同",
        )
    )
    db_session.commit()

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")
    assert generate_response.status_code == 201
    voucher_id = generate_response.json()["vouchers"][0]["id"]

    bank_response = client.get(f"/api/monthly-packages/{package.id}/bank-ledger")
    invoice_response = client.get(f"/api/monthly-packages/{package.id}/invoice-ledger")

    assert bank_response.status_code == 200
    assert invoice_response.status_code == 200
    assert bank_response.json()[0]["linked_vouchers"][0]["id"] == voucher_id
    assert bank_response.json()[0]["linked_vouchers"][0]["voucher_number"] == "未编号"
    assert bank_response.json()[0]["linked_vouchers"][0]["task_type"] == "FULL_MATCH"
    assert invoice_response.json()[0]["linked_vouchers"][0]["id"] == voucher_id
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest tests/test_voucher_api.py::test_source_ledger_rows_include_linked_voucher_ids -q
```

Expected: FAIL because `linked_vouchers` is not present in ledger row responses.

- [ ] **Step 3: Extend voucher schemas**

In `finwise-accounting/backend/app/schemas/voucher.py`, add this class after `VoucherGenerateResponse`:

```python
class VoucherLedgerLinkRead(BaseModel):
    id: UUID
    voucher_number: str
    status: str
    status_label: str
    summary: str
    task_type: str
    ai_confidence: int
```

Then add this field to both `BankLedgerRowRead` and `InvoiceLedgerRowRead`:

```python
linked_vouchers: list[VoucherLedgerLinkRead] = []
```

- [ ] **Step 4: Add linked voucher serialization**

In `finwise-accounting/backend/app/services/voucher_service.py`, add helper functions near `_linked_voucher_numbers`:

```python
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
```

In `list_bank_ledger()` and `list_invoice_ledger()`, where each row already sets `linked_voucher_numbers`, also set:

```python
"linked_vouchers": _linked_voucher_reads(row_vouchers),
```

Use the existing local variable that contains linked vouchers for that bank transaction or invoice. If the row currently calls `_linked_voucher_numbers(vouchers)` inline, assign `row_vouchers = bank_voucher_index.get(transaction.id, [])` or `row_vouchers = invoice_voucher_index.get(invoice.id, [])` first.

- [ ] **Step 5: Verify the API test passes**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest tests/test_voucher_api.py::test_source_ledger_rows_include_linked_voucher_ids -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/starryn/project/finwise
git add finwise-accounting/backend/app/schemas/voucher.py finwise-accounting/backend/app/services/voucher_service.py finwise-accounting/backend/tests/test_voucher_api.py
git commit -m "feat(vouchers): expose voucher links on source ledgers"
```

---

### Task 2: Kimi Voucher Preprocessing Service With Audit Trail

**Files:**
- Create: `finwise-accounting/backend/app/services/voucher_ai_preprocess_service.py`
- Modify: `finwise-accounting/backend/app/schemas/voucher.py`
- Modify: `finwise-accounting/backend/app/api/vouchers.py`
- Test: `finwise-accounting/backend/tests/test_voucher_api.py`

- [ ] **Step 1: Write backend tests for Kimi success and fallback**

Add these tests to `finwise-accounting/backend/tests/test_voucher_api.py`:

```python
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


def test_voucher_preprocess_endpoint_calls_kimi_client_and_records_audit(db_session, monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    enterprise, package = create_enterprise_with_package(db_session, company_name="昆山黛珂特电子科技有限公司")
    create_bank_transaction(
        db_session,
        package,
        transaction_date=date(2026, 4, 8),
        summary="电子转账 收到货款",
        counterparty_name="上海客户有限公司",
        debit_amount=Decimal("0"),
        credit_amount=Decimal("1130.00"),
    )
    create_invoice(
        db_session,
        package,
        invoice_direction="OUTPUT",
        invoice_date=date(2026, 4, 8),
        buyer_name="上海客户有限公司",
        seller_name=enterprise.name,
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
    )
    db_session.commit()

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
    assert payload["fallback_used"] is False
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


def test_voucher_preprocess_endpoint_falls_back_visibly_when_kimi_fails(db_session, monkeypatch):
    from app.services import voucher_ai_preprocess_service as service

    enterprise, package = create_enterprise_with_package(db_session)
    create_bank_transaction(
        db_session,
        package,
        transaction_date=date(2026, 4, 8),
        summary="电子转账 收到货款",
        counterparty_name="上海客户有限公司",
        debit_amount=Decimal("0"),
        credit_amount=Decimal("1130.00"),
    )
    create_invoice(
        db_session,
        package,
        invoice_direction="OUTPUT",
        invoice_date=date(2026, 4, 8),
        buyer_name="上海客户有限公司",
        seller_name=enterprise.name,
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
    )
    db_session.commit()

    stub = StubVoucherPreprocessClient(error=service.VoucherAiPreprocessUnavailableError("timeout"))
    monkeypatch.setattr(service, "create_default_voucher_preprocess_client", lambda: stub)

    response = client.post(f"/api/monthly-packages/{package.id}/vouchers/preprocess")

    assert response.status_code == 201
    payload = response.json()
    assert payload["ai_status"] == "FALLBACK"
    assert payload["used_kimi"] is True
    assert payload["fallback_used"] is True
    assert "AI 调用失败，已使用本地规则兜底" in payload["message"]
```

At the top of the file, add imports if missing:

```python
import json
from app.models import AuditLog
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest tests/test_voucher_api.py::test_voucher_preprocess_endpoint_calls_kimi_client_and_records_audit tests/test_voucher_api.py::test_voucher_preprocess_endpoint_falls_back_visibly_when_kimi_fails -q
```

Expected: FAIL because the endpoint and service do not exist.

- [ ] **Step 3: Add response schemas**

In `finwise-accounting/backend/app/schemas/voucher.py`, add:

```python
class VoucherPreprocessAuditRead(BaseModel):
    used_kimi: bool
    fallback_used: bool
    ai_status: str
    model: str
    input_bank_count: int
    input_invoice_count: int
    generated_task_counts: dict
    duration_ms: int
    error_summary: str = ""


class VoucherPreprocessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ai_status: str
    used_kimi: bool
    fallback_used: bool
    message: str
    created_vouchers: int
    vouchers: list[VoucherRead]
    audit: VoucherPreprocessAuditRead
```

- [ ] **Step 4: Implement the preprocessing service**

Create `finwise-accounting/backend/app/services/voucher_ai_preprocess_service.py` with these responsibilities:

```python
from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Protocol
from urllib import error, request
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AuditLog, BankTransaction, Enterprise, Invoice, MonthlyWorkPackage, Voucher
from app.services.voucher_service import VoucherDomainError, generate_voucher_drafts


class VoucherAiPreprocessUnavailableError(Exception):
    pass


class VoucherPreprocessClient(Protocol):
    def propose_voucher_tasks(self, payload: dict) -> dict:
        ...


class MoonshotVoucherPreprocessClient:
    def __init__(self, *, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def propose_voucher_tasks(self, payload: dict) -> dict:
        if not self.api_key:
            raise VoucherAiPreprocessUnavailableError("Moonshot API key is not configured.")
        body = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": VOUCHER_PREPROCESS_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        http_request = request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=90) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            return json.loads(response_data["choices"][0]["message"]["content"])
        except TimeoutError as exc:
            raise VoucherAiPreprocessUnavailableError("AI 服务响应超时") from exc
        except error.HTTPError as exc:
            raise VoucherAiPreprocessUnavailableError(f"AI 服务返回错误：HTTP {exc.code}") from exc
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise VoucherAiPreprocessUnavailableError("AI 服务暂时不可用") from exc
```

Use this exact prompt in the same file:

```python
VOUCHER_PREPROCESS_SYSTEM_PROMPT = (
    "你是代账公司的凭证预处理助手。只能根据脱敏后的金额、日期、方向、摘要关键词、发票方向、税额、"
    "对方别名和历史规则判断。不要输出企业全称、税号、银行账号或完整发票号。返回 JSON，格式为 "
    "{\"task_suggestions\":[{\"source_key\":\"string\",\"task_type\":\"FULL_MATCH|DIFFERENCE_COMPLETION|"
    "SINGLE_SOURCE|HISTORICAL_REVIEW\",\"confidence\":0-100,\"summary\":\"中文凭证摘要\","
    "\"reason\":\"中文原因\",\"bank_refs\":[\"T001\"],\"invoice_refs\":[\"I001\"],"
    "\"entries\":[{\"direction\":\"DEBIT|CREDIT\",\"account_code\":\"1002\",\"account_name\":\"银行存款\","
    "\"amount\":100.00}]}]}。不确定的任务 confidence 低于 80，并说明需要人工确认。"
)
```

Then add:

```python
def create_default_voucher_preprocess_client() -> VoucherPreprocessClient:
    settings = get_settings()
    return MoonshotVoucherPreprocessClient(
        api_key=settings.moonshot_api_key,
        base_url=settings.moonshot_base_url,
        model=settings.moonshot_model,
    )


def run_voucher_ai_preprocessing(
    db: Session,
    *,
    monthly_work_package_id: UUID,
    ai_client: VoucherPreprocessClient | None = None,
) -> dict:
    started_at = time.monotonic()
    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    if package is None:
        raise VoucherDomainError("Monthly work package not found in current organization.")
    enterprise = db.get(Enterprise, package.enterprise_id)
    payload = build_voucher_preprocess_payload(db, package=package, enterprise=enterprise)
    settings = get_settings()
    client = ai_client or create_default_voucher_preprocess_client()
    ai_status = "SUCCESS"
    fallback_used = False
    error_summary = ""
    ai_response = {"task_suggestions": []}
    try:
        ai_response = client.propose_voucher_tasks(payload)
    except VoucherAiPreprocessUnavailableError as exc:
        ai_status = "FALLBACK"
        fallback_used = True
        error_summary = str(exc)

    generated = generate_voucher_drafts(db, monthly_work_package_id=package.id)
    vouchers = generated["vouchers"]
    _attach_preprocess_metadata(vouchers, ai_response=ai_response, ai_status=ai_status)

    audit = {
        "used_kimi": True,
        "fallback_used": fallback_used,
        "ai_status": ai_status,
        "model": settings.moonshot_model,
        "input_bank_count": len(payload["bank_transactions"]),
        "input_invoice_count": len(payload["invoices"]),
        "generated_task_counts": _task_counts(vouchers),
        "duration_ms": int((time.monotonic() - started_at) * 1000),
        "error_summary": error_summary,
    }
    db.add(
        AuditLog(
            organization_id=package.organization_id,
            monthly_work_package_id=package.id,
            actor="system",
            action="VOUCHER_AI_PREPROCESS",
            before_data={
                "payload_summary": {
                    "bank_transactions": audit["input_bank_count"],
                    "invoices": audit["input_invoice_count"],
                }
            },
            after_data=audit,
        )
    )
    db.commit()
    return {
        "ai_status": ai_status,
        "used_kimi": True,
        "fallback_used": fallback_used,
        "message": "AI 预处理完成" if not fallback_used else "AI 调用失败，已使用本地规则兜底",
        "created_vouchers": generated["created_vouchers"],
        "vouchers": vouchers,
        "audit": audit,
    }
```

Add payload helpers in the same file:

```python
def build_voucher_preprocess_payload(db: Session, *, package: MonthlyWorkPackage, enterprise: Enterprise | None) -> dict:
    transactions = list(
        db.scalars(
            select(BankTransaction)
            .where(BankTransaction.monthly_work_package_id == package.id)
            .order_by(BankTransaction.transaction_date, BankTransaction.id)
        )
    )
    invoices = list(
        db.scalars(
            select(Invoice)
            .where(Invoice.monthly_work_package_id == package.id)
            .order_by(Invoice.invoice_date, Invoice.id)
        )
    )
    party_aliases: dict[str, str] = {}
    return {
        "package": {
            "period": package.period,
            "enterprise_alias": "企业主体",
            "industry": enterprise.industry if enterprise else "",
        },
        "bank_transactions": [
            {
                "ref": f"T{index:03d}",
                "date": item.transaction_date.isoformat(),
                "direction": "RECEIPT" if _money(item.credit_amount) > 0 else "PAYMENT",
                "amount": str(abs(_money(item.credit_amount) - _money(item.debit_amount))),
                "counterparty_alias": _alias_for(item.counterparty_name, party_aliases, prefix="交易对方"),
                "summary_keywords": _safe_words(item.summary),
            }
            for index, item in enumerate(transactions, start=1)
        ],
        "invoices": [
            {
                "ref": f"I{index:03d}",
                "date": item.invoice_date.isoformat(),
                "direction": item.invoice_direction,
                "amount": str(_money(item.amount)),
                "tax_amount": str(_money(item.tax_amount)),
                "total_amount": str(_money(item.total_amount)),
                "counterparty_alias": _alias_for(_invoice_counterparty_name(item, enterprise_name=enterprise.name if enterprise else ""), party_aliases, prefix="交易对方"),
            }
            for index, item in enumerate(invoices, start=1)
        ],
    }
```

Add small pure helpers:

```python
def _money(value) -> Decimal:
    return Decimal(str(value or "0")).quantize(Decimal("0.01"))


def _safe_words(text: str) -> str:
    return " ".join(str(text or "").replace("\n", " ").split())[:80]


def _alias_for(name: str, aliases: dict[str, str], *, prefix: str) -> str:
    key = _safe_words(name) or "空白对方"
    if key not in aliases:
        aliases[key] = f"{prefix}{len(aliases) + 1}"
    return aliases[key]


def _invoice_counterparty_name(invoice: Invoice, *, enterprise_name: str) -> str:
    if invoice.invoice_direction == "OUTPUT":
        return invoice.buyer_name if invoice.buyer_name != enterprise_name else invoice.seller_name
    return invoice.seller_name if invoice.seller_name != enterprise_name else invoice.buyer_name


def _task_counts(vouchers: list[Voucher]) -> dict:
    counts: dict[str, int] = {}
    for voucher in vouchers:
        task_type = str((voucher.source_data or {}).get("voucher_task_type") or "UNKNOWN")
        counts[task_type] = counts.get(task_type, 0) + 1
    return counts


def _attach_preprocess_metadata(vouchers: list[Voucher], *, ai_response: dict, ai_status: str) -> None:
    suggestions = ai_response.get("task_suggestions") if isinstance(ai_response, dict) else []
    suggestion_by_type = {
        str(item.get("task_type")): item
        for item in suggestions or []
        if isinstance(item, dict) and item.get("task_type")
    }
    for voucher in vouchers:
        source_data = dict(voucher.source_data or {})
        task_type = str(source_data.get("voucher_task_type") or "")
        suggestion = suggestion_by_type.get(task_type)
        source_data["ai_preprocess"] = {
            "ai_status": ai_status,
            "kimi_suggestion": suggestion or {},
        }
        if suggestion and suggestion.get("reason"):
            voucher.ai_reason = str(suggestion["reason"])
        if suggestion and suggestion.get("confidence") is not None:
            voucher.ai_confidence = max(0, min(100, int(suggestion["confidence"])))
        voucher.source_data = source_data
```

- [ ] **Step 5: Add API route**

In `finwise-accounting/backend/app/api/vouchers.py`, import:

```python
from app.schemas.voucher import VoucherPreprocessResponse
from app.services.voucher_ai_preprocess_service import run_voucher_ai_preprocessing
```

Then add below `generate_vouchers_endpoint`:

```python
@router.post(
    "/api/monthly-packages/{package_id}/vouchers/preprocess",
    response_model=VoucherPreprocessResponse,
    status_code=status.HTTP_201_CREATED,
)
def preprocess_vouchers_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return run_voucher_ai_preprocessing(db, monthly_work_package_id=package_id)
    except VoucherValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

- [ ] **Step 6: Verify backend tests pass**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest tests/test_voucher_api.py::test_voucher_preprocess_endpoint_calls_kimi_client_and_records_audit tests/test_voucher_api.py::test_voucher_preprocess_endpoint_falls_back_visibly_when_kimi_fails -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/starryn/project/finwise
git add finwise-accounting/backend/app/services/voucher_ai_preprocess_service.py finwise-accounting/backend/app/schemas/voucher.py finwise-accounting/backend/app/api/vouchers.py finwise-accounting/backend/tests/test_voucher_api.py
git commit -m "feat(vouchers): add kimi preprocessing audit"
```

---

### Task 3: Frontend API Client and Source Ledger Components

**Files:**
- Modify: `finwise-accounting/frontend/src/api/client.js`
- Modify: `finwise-accounting/frontend/src/api/client.spec.js`
- Create: `finwise-accounting/frontend/src/components/source-ledgers/ledgerFormatters.js`
- Create: `finwise-accounting/frontend/src/components/source-ledgers/BankLedgerTable.vue`
- Create: `finwise-accounting/frontend/src/components/source-ledgers/InvoiceLedgerTable.vue`
- Modify: `finwise-accounting/frontend/src/views/SourceLedgerView.spec.js`
- Modify: `finwise-accounting/frontend/src/views/BankLedgerView.vue`
- Modify: `finwise-accounting/frontend/src/views/InvoiceLedgerView.vue`

- [ ] **Step 1: Write source-level tests**

In `finwise-accounting/frontend/src/api/client.spec.js`, extend the AI timeout test:

```js
expect(source).toContain('preprocess: (packageId) => apiClient.post(`/monthly-packages/${packageId}/vouchers/preprocess`, undefined, { timeout: AI_REQUEST_TIMEOUT_MS })')
```

In `finwise-accounting/frontend/src/views/SourceLedgerView.spec.js`, add:

```js
it('uses reusable source ledger components that emit row selection for voucher workbench reuse', () => {
  const bankComponent = readFileSync(resolve(__dirname, '../components/source-ledgers/BankLedgerTable.vue'), 'utf8')
  const invoiceComponent = readFileSync(resolve(__dirname, '../components/source-ledgers/InvoiceLedgerTable.vue'), 'utf8')
  expect(bankComponent).toContain("defineEmits(['row-select'])")
  expect(invoiceComponent).toContain("defineEmits(['row-select'])")
  expect(bankComponent).toContain('linked_vouchers')
  expect(invoiceComponent).toContain('linked_vouchers')
  expect(bankComponent).toContain('凭证号')
  expect(invoiceComponent).toContain('凭证号')
})
```

- [ ] **Step 2: Run failing frontend source tests**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run test -- --run src/api/client.spec.js src/views/SourceLedgerView.spec.js
```

Expected: FAIL because the API method and components do not exist.

- [ ] **Step 3: Add API method**

In `finwise-accounting/frontend/src/api/client.js`, change the `vouchers` object to include:

```js
preprocess: (packageId) => apiClient.post(`/monthly-packages/${packageId}/vouchers/preprocess`, undefined, { timeout: AI_REQUEST_TIMEOUT_MS }),
```

- [ ] **Step 4: Add shared formatters**

Create `finwise-accounting/frontend/src/components/source-ledgers/ledgerFormatters.js`:

```js
export function formatAmount(value) {
  const number = Number(value || 0)
  return number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function voucherStatusTag(status) {
  if (status === 'CONFIRMED') return 'success'
  if (status === 'PENDING_CONFIRMATION') return 'warning'
  if (status === 'REJECTED') return 'danger'
  return 'info'
}

export function matchingStatusTag(status) {
  if (status === 'MATCHED') return 'success'
  if (status === 'PARTIAL') return 'warning'
  return 'info'
}

export function linkedVoucherLabel(row) {
  const links = row?.linked_vouchers || []
  if (!links.length) return '-'
  return links.map((item) => item.voucher_number || '未编号').join('、')
}

export function sourceRowMatchesKeyword(row, keyword, fields) {
  const text = String(keyword || '').trim()
  if (!text) return true
  return fields.map((field) => row?.[field] ?? '').join(' ').includes(text)
}
```

- [ ] **Step 5: Create `BankLedgerTable.vue`**

Create `finwise-accounting/frontend/src/components/source-ledgers/BankLedgerTable.vue` with:

```vue
<template>
  <div class="ledger-table-scroll">
    <el-table
      v-loading="loading"
      :data="rows"
      class="ledger-table bank-ledger-table"
      stripe
      highlight-current-row
      empty-text="暂无资金流水"
      @row-click="emit('row-select', $event)"
    >
      <el-table-column prop="transaction_date" label="日期" width="112" />
      <el-table-column prop="summary" label="摘要" min-width="180" show-overflow-tooltip />
      <el-table-column prop="direction_label" label="收支方向" width="104" />
      <el-table-column prop="counterparty_name" label="交易对方" min-width="190" show-overflow-tooltip />
      <el-table-column label="收入金额" width="130" align="right">
        <template #default="{ row }">{{ formatAmount(row.credit_amount) }}</template>
      </el-table-column>
      <el-table-column label="支出金额" width="130" align="right">
        <template #default="{ row }">{{ formatAmount(row.debit_amount) }}</template>
      </el-table-column>
      <el-table-column label="余额" width="130" align="right">
        <template #default="{ row }">{{ row.balance == null ? '-' : formatAmount(row.balance) }}</template>
      </el-table-column>
      <el-table-column label="匹配状态" width="118">
        <template #default="{ row }">
          <el-tag :type="matchingStatusTag(row.matching_status)" size="small">{{ row.matching_status_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="凭证状态" width="118">
        <template #default="{ row }">
          <el-tag :type="voucherStatusTag(row.voucher_status)" size="small">{{ row.voucher_status_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="linked_invoice_count" label="关联发票" width="96" align="right" />
      <el-table-column label="凭证号" width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ linkedVoucherLabel(row) }}</template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { formatAmount, linkedVoucherLabel, matchingStatusTag, voucherStatusTag } from './ledgerFormatters'

defineProps({
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['row-select'])
</script>

<style scoped>
.ledger-table-scroll {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  scrollbar-color: var(--fw-brand) #eaf2ff;
  scrollbar-width: thin;
}
.ledger-table-scroll::-webkit-scrollbar { height: 12px; }
.ledger-table-scroll::-webkit-scrollbar-track { background: #eaf2ff; }
.ledger-table-scroll::-webkit-scrollbar-thumb {
  border: 2px solid #eaf2ff;
  border-radius: 999px;
  background: var(--fw-brand);
}
.ledger-table {
  width: 100%;
  min-width: 1420px;
}
</style>
```

- [ ] **Step 6: Create `InvoiceLedgerTable.vue`**

Create `finwise-accounting/frontend/src/components/source-ledgers/InvoiceLedgerTable.vue` with the same structure, using columns:

```vue
<el-table-column prop="invoice_direction_label" label="发票方向" width="104" />
<el-table-column prop="invoice_number" label="发票号码" min-width="180" show-overflow-tooltip />
<el-table-column prop="invoice_date" label="开票日期" width="112" />
<el-table-column prop="counterparty_role" label="对方角色" width="96" />
<el-table-column prop="counterparty_name" label="对方名称" min-width="190" show-overflow-tooltip />
<el-table-column label="金额" width="130" align="right">
  <template #default="{ row }">{{ formatAmount(row.amount) }}</template>
</el-table-column>
<el-table-column label="税额" width="130" align="right">
  <template #default="{ row }">{{ formatAmount(row.tax_amount) }}</template>
</el-table-column>
<el-table-column label="价税合计" width="130" align="right">
  <template #default="{ row }">{{ formatAmount(row.total_amount) }}</template>
</el-table-column>
<el-table-column label="匹配状态" width="118">
  <template #default="{ row }">
    <el-tag :type="matchingStatusTag(row.matching_status)" size="small">{{ row.matching_status_label }}</el-tag>
  </template>
</el-table-column>
<el-table-column label="凭证状态" width="118">
  <template #default="{ row }">
    <el-tag :type="voucherStatusTag(row.voucher_status)" size="small">{{ row.voucher_status_label }}</el-tag>
  </template>
</el-table-column>
<el-table-column prop="linked_bank_count" label="关联流水" width="96" align="right" />
<el-table-column label="凭证号" width="140" show-overflow-tooltip>
  <template #default="{ row }">{{ linkedVoucherLabel(row) }}</template>
</el-table-column>
```

Use:

```js
import { formatAmount, linkedVoucherLabel, matchingStatusTag, voucherStatusTag } from './ledgerFormatters'
defineProps({ rows: { type: Array, default: () => [] }, loading: { type: Boolean, default: false } })
const emit = defineEmits(['row-select'])
```

- [ ] **Step 7: Refactor standalone views to use components**

In `BankLedgerView.vue`, replace the inline `<el-table>` block with:

```vue
<BankLedgerTable :rows="filteredRows" :loading="isLoading" />
```

Import:

```js
import BankLedgerTable from '../components/source-ledgers/BankLedgerTable.vue'
import { sourceRowMatchesKeyword } from '../components/source-ledgers/ledgerFormatters'
```

Update filter body to:

```js
return bankRows.value.filter((row) =>
  sourceRowMatchesKeyword(row, text, [
    'transaction_date',
    'summary',
    'direction_label',
    'counterparty_name',
    'transaction_amount',
    'matching_status_label',
    'voucher_status_label',
  ]),
)
```

In `InvoiceLedgerView.vue`, replace the inline `<el-table>` with:

```vue
<InvoiceLedgerTable :rows="filteredRows" :loading="isLoading" />
```

Import:

```js
import InvoiceLedgerTable from '../components/source-ledgers/InvoiceLedgerTable.vue'
import { sourceRowMatchesKeyword } from '../components/source-ledgers/ledgerFormatters'
```

Use `sourceRowMatchesKeyword` after the direction filter.

- [ ] **Step 8: Verify frontend source tests pass**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run test -- --run src/api/client.spec.js src/views/SourceLedgerView.spec.js
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
cd /Users/starryn/project/finwise
git add finwise-accounting/frontend/src/api/client.js finwise-accounting/frontend/src/api/client.spec.js finwise-accounting/frontend/src/components/source-ledgers finwise-accounting/frontend/src/views/BankLedgerView.vue finwise-accounting/frontend/src/views/InvoiceLedgerView.vue finwise-accounting/frontend/src/views/SourceLedgerView.spec.js
git commit -m "feat(frontend): reuse source ledger tables"
```

---

### Task 4: Embed Bank and Invoice Ledgers in Voucher Workbench

**Files:**
- Modify: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.vue`
- Modify: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.spec.js`

- [ ] **Step 1: Write source-level test for the workbench layout**

In `VoucherWorkbenchView.spec.js`, replace expectations for the old list with:

```js
it('uses source-ledger tabs as the primary voucher workbench list', () => {
  expect(viewSource).toContain('按资金流水整理')
  expect(viewSource).toContain('按发票台账整理')
  expect(viewSource).toContain('<BankLedgerTable')
  expect(viewSource).toContain('<InvoiceLedgerTable')
  expect(viewSource).toContain('@row-select="selectBankLedgerRow"')
  expect(viewSource).toContain('@row-select="selectInvoiceLedgerRow"')
  expect(viewSource).not.toContain('待处理凭证列表')
})
```

Update the button test to:

```js
expect(viewSource).toContain('AI 预处理')
expect(viewSource).toContain('async function preprocessVouchers()')
expect(viewSource).toContain('api.vouchers.preprocess')
expect(viewSource).not.toContain('生成草稿并 AI 推荐')
```

- [ ] **Step 2: Run failing workbench test**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run test -- --run src/views/VoucherWorkbenchView.spec.js
```

Expected: FAIL because the old voucher list still exists.

- [ ] **Step 3: Add ledger state and loaders**

In `VoucherWorkbenchView.vue`, import:

```js
import BankLedgerTable from '../components/source-ledgers/BankLedgerTable.vue'
import InvoiceLedgerTable from '../components/source-ledgers/InvoiceLedgerTable.vue'
import { sourceRowMatchesKeyword } from '../components/source-ledgers/ledgerFormatters'
```

Add state:

```js
const activeLedgerTab = ref('bank')
const bankLedgerRows = ref([])
const invoiceLedgerRows = ref([])
const bankLedgerKeyword = ref('')
const invoiceLedgerKeyword = ref('')
const invoiceDirectionFilter = ref('all')
const preprocessAudit = ref(null)
```

Add computed filters:

```js
const filteredBankLedgerRows = computed(() =>
  bankLedgerRows.value.filter((row) =>
    sourceRowMatchesKeyword(row, bankLedgerKeyword.value, [
      'transaction_date',
      'summary',
      'direction_label',
      'counterparty_name',
      'transaction_amount',
      'matching_status_label',
      'voucher_status_label',
    ]),
  ),
)

const filteredInvoiceLedgerRows = computed(() =>
  invoiceLedgerRows.value.filter((row) => {
    if (invoiceDirectionFilter.value !== 'all' && row.invoice_direction !== invoiceDirectionFilter.value) return false
    return sourceRowMatchesKeyword(row, invoiceLedgerKeyword.value, [
      'invoice_direction_label',
      'invoice_number',
      'invoice_date',
      'counterparty_role',
      'counterparty_name',
      'total_amount',
      'matching_status_label',
      'voucher_status_label',
    ])
  }),
)
```

In `loadVouchers`, load four requests:

```js
const [voucherResponse, summaryResponse, bankLedgerResponse, invoiceLedgerResponse] = await Promise.all([
  api.vouchers.list(packageId),
  api.sourceLedgers.summary(packageId),
  api.sourceLedgers.bank(packageId),
  api.sourceLedgers.invoices(packageId),
])
vouchers.value = normalizeVoucherList(voucherResponse.data)
ledgerSummary.value = normalizeLedgerSummary(summaryResponse.data)
bankLedgerRows.value = bankLedgerResponse.data || []
invoiceLedgerRows.value = invoiceLedgerResponse.data || []
```

In `clearVouchers`, clear `bankLedgerRows`, `invoiceLedgerRows`, and `preprocessAudit`.

- [ ] **Step 4: Replace left voucher list template**

Replace the `voucher-list-card` content with:

```vue
<div class="voucher-list-card source-workbench-card">
  <div class="list-header">
    <div>
      <strong>原始台账凭证整理</strong>
      <span>从资金流水或发票台账进入凭证核对</span>
    </div>
    <el-segmented
      v-model="activeLedgerTab"
      :options="[
        { label: '按资金流水整理', value: 'bank' },
        { label: '按发票台账整理', value: 'invoice' },
      ]"
      class="voucher-filter"
    />
  </div>

  <div v-if="activeLedgerTab === 'bank'" class="ledger-toolbar">
    <el-input v-model="bankLedgerKeyword" clearable placeholder="搜索日期、摘要、对方、金额" />
  </div>
  <div v-else class="ledger-toolbar">
    <el-select v-model="invoiceDirectionFilter" class="direction-filter" placeholder="发票方向">
      <el-option label="全部发票" value="all" />
      <el-option label="进项发票" value="INPUT" />
      <el-option label="销项发票" value="OUTPUT" />
    </el-select>
    <el-input v-model="invoiceLedgerKeyword" clearable placeholder="搜索发票号、对方、金额" />
  </div>

  <BankLedgerTable
    v-if="activeLedgerTab === 'bank'"
    :rows="filteredBankLedgerRows"
    :loading="isLoading"
    @row-select="selectBankLedgerRow"
  />
  <InvoiceLedgerTable
    v-else
    :rows="filteredInvoiceLedgerRows"
    :loading="isLoading"
    @row-select="selectInvoiceLedgerRow"
  />
</div>
```

- [ ] **Step 5: Select vouchers from ledger rows**

Add functions:

```js
function selectBankLedgerRow(row) {
  selectVoucherFromLedgerRow(row, '资金流水')
}

function selectInvoiceLedgerRow(row) {
  selectVoucherFromLedgerRow(row, '发票')
}

function selectVoucherFromLedgerRow(row, sourceLabel) {
  const linkedVoucherId = firstLinkedVoucherId(row)
  if (linkedVoucherId) {
    selectedVoucherId.value = linkedVoucherId
    return
  }
  ElMessage.warning(`${sourceLabel}暂未生成凭证任务，请先点击 AI 预处理`)
}

function firstLinkedVoucherId(row) {
  const links = row?.linked_vouchers || []
  const pending = links.find((item) => item.status === 'PENDING_CONFIRMATION')
  return pending?.id || links[0]?.id || ''
}
```

- [ ] **Step 6: Rename and rewire AI action**

Change button text to `AI 预处理` and handler to `preprocessVouchers`.

Replace `generateVouchers()` with:

```js
async function preprocessVouchers() {
  const packageId = activePackageId.value
  if (!packageId) {
    ElMessage.warning('请先选择企业主体和工作期间')
    return
  }
  isGenerating.value = true
  try {
    const response = await api.vouchers.preprocess(packageId)
    if (packageId !== activePackageId.value) return
    preprocessAudit.value = response.data?.audit || null
    const generatedVouchers = normalizeVoucherList(response.data)
    const createdVoucherCount = Number(response.data?.created_vouchers ?? generatedVouchers.length)
    await workspace.loadWorkspace(packageId)
    const didLoadCurrentPackage = await loadVouchers(packageId)
    if (!didLoadCurrentPackage || packageId !== activePackageId.value) return
    selectGeneratedVoucher(generatedVouchers)
    if (response.data?.fallback_used) {
      ElMessage.warning(response.data?.message || 'AI 调用失败，已使用本地规则兜底')
    } else {
      ElMessage.success(`AI 预处理完成，本次新增 ${createdVoucherCount} 张凭证任务`)
    }
  } catch (error) {
    if (packageId !== activePackageId.value) return
    ElMessage.error(error?.response?.data?.detail || error?.message || 'AI 预处理失败')
  } finally {
    isGenerating.value = false
  }
}
```

Update flow labels:

```vue
<strong>AI 预处理</strong>
<small>{{ vouchers.length ? `已形成 ${vouchers.length} 张凭证任务` : '全量比对流水、发票和历史规则' }}</small>
```

```vue
<strong>AI 推荐处理</strong>
<small>{{ hasAiSuggestion ? '已给出摘要、科目、金额和判断说明' : '预处理后展示 AI 置信度和说明' }}</small>
```

- [ ] **Step 7: Add fallback/audit visible status**

Under the flow or summary cards, add:

```vue
<el-alert
  v-if="preprocessAudit"
  class="preprocess-alert"
  :type="preprocessAudit.fallback_used ? 'warning' : 'success'"
  :closable="false"
  show-icon
>
  <template #title>
    {{ preprocessAudit.fallback_used ? 'AI 调用失败，已使用本地规则兜底' : 'Kimi AI 预处理已完成' }}
  </template>
  <template #default>
    模型：{{ preprocessAudit.model }}；流水 {{ preprocessAudit.input_bank_count }} 条；发票 {{ preprocessAudit.input_invoice_count }} 张；耗时 {{ preprocessAudit.duration_ms }}ms
  </template>
</el-alert>
```

- [ ] **Step 8: Verify workbench source tests pass**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run test -- --run src/views/VoucherWorkbenchView.spec.js
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
cd /Users/starryn/project/finwise
git add finwise-accounting/frontend/src/views/VoucherWorkbenchView.vue finwise-accounting/frontend/src/views/VoucherWorkbenchView.spec.js
git commit -m "feat(vouchers): embed source ledgers in workbench"
```

---

### Task 5: Regression Tests and Browser Flow Verification

**Files:**
- Modify: `finwise-accounting/backend/tests/test_end_to_end_monthly_flow.py`
- Modify: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.spec.js`
- Use browser target: `http://127.0.0.1:5174/vouchers`

- [ ] **Step 1: Add backend end-to-end regression**

In `finwise-accounting/backend/tests/test_end_to_end_monthly_flow.py`, add a test that creates one matched voucher, one bank-only voucher and one invoice-only voucher, then calls `/vouchers/preprocess`, `/bank-ledger`, `/invoice-ledger`, and `/vouchers`.

Assert:

```python
assert preprocess_payload["used_kimi"] is True
assert "audit" in preprocess_payload
assert len(voucher_payload) >= 3
assert any(row["linked_vouchers"] for row in bank_payload)
assert any(row["linked_vouchers"] for row in invoice_payload)
assert any(voucher["source_data"].get("voucher_task_type") == "SINGLE_SOURCE" for voucher in voucher_payload)
```

Use the same `StubVoucherPreprocessClient` monkeypatch pattern from Task 2 so the test does not call the network.

- [ ] **Step 2: Run backend voucher suite**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest tests/test_voucher_service.py tests/test_voucher_api.py tests/test_end_to_end_monthly_flow.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend test suite**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run test -- --run
npm run build
```

Expected: PASS and build succeeds.

- [ ] **Step 4: Start local services**

If services are not already running, start backend and frontend:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001
```

In a second session:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run dev -- --host 127.0.0.1 --port 5174
```

Expected: backend on `http://127.0.0.1:8001`, frontend on `http://127.0.0.1:5174`.

- [ ] **Step 5: Browser verify the critical flow**

Use the in-app browser or Playwright to open:

```text
http://127.0.0.1:5174/vouchers
```

Verify visually and functionally:

- Button says `AI 预处理`.
- Click `AI 预处理`; observe API path `/api/monthly-packages/{id}/vouchers/preprocess`.
- Confirm no path contains `[object PointerEvent]`.
- After completion, the visible alert says either `Kimi AI 预处理已完成` or `AI 调用失败，已使用本地规则兜底`.
- Left workbench shows `按资金流水整理` and `按发票台账整理`.
- Click one bank row with linked voucher; right panel updates to that voucher.
- Switch to invoice tab; click one invoice row with linked voucher; right panel updates.
- Confirm/reopen/reject still gives visible feedback.
- Narrow the browser to split-screen width; table action/status columns remain reachable through visible horizontal scrolling.

- [ ] **Step 6: Commit test adjustments**

```bash
cd /Users/starryn/project/finwise
git add finwise-accounting/backend/tests/test_end_to_end_monthly_flow.py finwise-accounting/frontend/src/views/VoucherWorkbenchView.spec.js
git commit -m "test(vouchers): cover source-ledger workbench flow"
```

---

## Self-Review

**Spec coverage:**

- “AI 预处理” button naming: Task 4.
- Kimi API call from `.env` / settings: Task 2 uses `settings.moonshot_api_key`, `moonshot_base_url`, `moonshot_model`.
- Full bank + invoice comparison payload: Task 2 sends all package transactions and invoices in desensitized form.
- Fallback visible and not disguised as AI success: Task 2 response and Task 4 alert.
- Audit proof of Kimi call: Task 2 writes `AuditLog` with action `VOUCHER_AI_PREPROCESS`.
- Embedded bank/invoice workbench tabs: Task 4.
- Standalone bank/invoice menus remain: Task 3 refactors but keeps views.
- Row click opens voucher panel: Task 4.
- Browser verification for critical controls: Task 5.

**Placeholder scan:** No forbidden placeholder markers or deferred unspecified implementation remains in this plan.

**Type consistency:** Backend response names `ai_status`, `used_kimi`, `fallback_used`, `created_vouchers`, `audit`, and `vouchers` are used consistently by API, frontend client and Vue view.
