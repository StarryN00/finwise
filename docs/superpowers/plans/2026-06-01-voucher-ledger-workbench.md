# Voucher Ledger Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first complete voucher preparation loop for 昆山黛珂特电子科技有限公司 2026-04, covering full bank and invoice ledgers, AI-organized voucher tasks, user confirmation, and rule retention.

**Architecture:** Keep the existing `Voucher` model as the persisted voucher draft/task record. Add ledger read APIs that derive status from existing vouchers and match records, and extend voucher generation so every bank transaction and invoice becomes visible as matched, difference, single-sided, or historical-review work. Add two source-ledger pages plus a richer voucher workbench summary without changing unrelated old code.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Vue 3, Element Plus, Vitest, Pytest, Playwright/browser verification.

---

### Task 1: Backend Ledger Read APIs

**Files:**
- Modify: `finwise-accounting/backend/app/schemas/voucher.py`
- Modify: `finwise-accounting/backend/app/services/voucher_service.py`
- Modify: `finwise-accounting/backend/app/api/vouchers.py`
- Test: `finwise-accounting/backend/tests/test_voucher_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests that create a monthly package with bank transactions, input invoices, output invoices, and vouchers, then assert:

```python
def test_list_bank_ledger_api_returns_processing_status(client, db_session):
    package = create_package_with_bank_and_invoice_data(db_session)
    response = client.get(f"/api/monthly-packages/{package.id}/bank-ledger")
    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["source_type"] == "BANK"
    assert rows[0]["direction_label"] in ["收入", "支出"]
    assert "voucher_status_label" in rows[0]
    assert "matching_status_label" in rows[0]


def test_list_invoice_ledger_api_returns_counterparty_by_direction(client, db_session):
    package = create_package_with_bank_and_invoice_data(db_session)
    response = client.get(f"/api/monthly-packages/{package.id}/invoice-ledger")
    assert response.status_code == 200
    rows = response.json()
    input_row = next(row for row in rows if row["invoice_direction"] == "INPUT")
    output_row = next(row for row in rows if row["invoice_direction"] == "OUTPUT")
    assert input_row["counterparty_role"] == "销售方"
    assert output_row["counterparty_role"] == "购买方"
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest tests/test_voucher_api.py::test_list_bank_ledger_api_returns_processing_status tests/test_voucher_api.py::test_list_invoice_ledger_api_returns_counterparty_by_direction -q
```

Expected: fail with missing route or schema.

- [ ] **Step 3: Add schemas**

Add `BankLedgerRowRead`, `InvoiceLedgerRowRead`, and `VoucherLedgerSummaryRead` with Chinese-ready labels:

```python
class BankLedgerRowRead(BaseModel):
    id: UUID
    source_type: str = "BANK"
    transaction_date: date
    summary: str
    direction: str
    direction_label: str
    counterparty_name: str
    debit_amount: Decimal
    credit_amount: Decimal
    transaction_amount: Decimal
    balance: Optional[Decimal]
    matching_status: str
    matching_status_label: str
    voucher_status: str
    voucher_status_label: str
    linked_invoice_count: int = 0
    linked_voucher_count: int = 0
    linked_voucher_numbers: list[str] = []


class InvoiceLedgerRowRead(BaseModel):
    id: UUID
    source_type: str = "INVOICE"
    invoice_direction: str
    invoice_direction_label: str
    invoice_number: str
    invoice_date: date
    counterparty_name: str
    counterparty_role: str
    amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    matching_status: str
    matching_status_label: str
    voucher_status: str
    voucher_status_label: str
    linked_bank_count: int = 0
    linked_voucher_count: int = 0
    linked_voucher_numbers: list[str] = []


class VoucherLedgerSummaryRead(BaseModel):
    bank_total_count: int
    bank_processed_count: int
    bank_pending_count: int
    invoice_total_count: int
    invoice_processed_count: int
    invoice_pending_count: int
    voucher_total_count: int
    pending_task_count: int
    difference_total_amount: Decimal
    single_source_total_amount: Decimal
```

- [ ] **Step 4: Implement service functions**

Add `list_bank_ledger()`, `list_invoice_ledger()`, and `get_voucher_ledger_summary()` that:

- Load sources by `monthly_work_package_id`.
- Detect linked vouchers from `Voucher.source_data.bank_transaction_id`, `bank_transaction_ids`, `invoice_id`, and `invoice_ids`.
- Detect linked matches from `MatchRecord`.
- Return Chinese status labels and never expose raw enum labels as primary UI text.

- [ ] **Step 5: Add API routes**

Add:

```python
@router.get("/api/monthly-packages/{package_id}/bank-ledger", response_model=list[BankLedgerRowRead])
def list_bank_ledger_endpoint(package_id: UUID, db: Session = Depends(get_db)): ...

@router.get("/api/monthly-packages/{package_id}/invoice-ledger", response_model=list[InvoiceLedgerRowRead])
def list_invoice_ledger_endpoint(package_id: UUID, db: Session = Depends(get_db)): ...

@router.get("/api/monthly-packages/{package_id}/voucher-ledger-summary", response_model=VoucherLedgerSummaryRead)
def voucher_ledger_summary_endpoint(package_id: UUID, db: Session = Depends(get_db)): ...
```

- [ ] **Step 6: Run backend tests**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest tests/test_voucher_api.py -q
```

Expected: pass.

### Task 2: Full Voucher Task Generation Coverage

**Files:**
- Modify: `finwise-accounting/backend/app/services/voucher_service.py`
- Test: `finwise-accounting/backend/tests/test_voucher_service.py`
- Test: `finwise-accounting/backend/tests/test_voucher_api.py`

- [ ] **Step 1: Write failing coverage tests**

Add tests that assert voucher generation covers:

- exact matched voucher
- one invoice with multiple bank transactions
- one bank transaction with multiple invoices
- unmatched bank transaction as single-source treatment
- unmatched invoice as single-source treatment
- amount mismatch as difference treatment

Expected source group types:

```python
assert source_data["source_group_type"] in [
    "FULL_MATCH",
    "ONE_INVOICE_MULTIPLE_BANK",
    "ONE_BANK_MULTIPLE_INVOICES",
    "BANK_ONLY",
    "INVOICE_ONLY",
    "DIFFERENCE_COMPLETION",
]
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest tests/test_voucher_service.py -q
```

Expected: fail for missing full coverage or missing group type.

- [ ] **Step 3: Extend generation without duplicate source use**

Update `generate_voucher_drafts()` so after confirmed match vouchers it:

- Builds a used-source set from non-rejected vouchers.
- Generates composite vouchers for exact one-to-many and many-to-one combinations.
- Generates difference-completion vouchers when both sides share a plausible counterparty/date window but totals do not balance.
- Generates single-source bank and invoice vouchers for all remaining sources.
- Preserves existing idempotency by source key.

- [ ] **Step 4: Persist explainable source data**

Each voucher must include:

```python
source_data = {
    "source_group_type": "...",
    "bank_transaction_ids": [...],
    "invoice_ids": [...],
    "voucher_task_type": "FULL_MATCH|DIFFERENCE_COMPLETION|SINGLE_SOURCE|HISTORICAL_REVIEW",
    "difference_amount": "0.00",
    "accounting_treatment": {...},
    "rule_memory": {...},
}
```

- [ ] **Step 5: Run voucher tests**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest tests/test_voucher_service.py tests/test_voucher_api.py -q
```

Expected: pass.

### Task 3: API Client, Routes, And Source Ledger Pages

**Files:**
- Modify: `finwise-accounting/frontend/src/api/client.js`
- Modify: `finwise-accounting/frontend/src/router/index.js`
- Modify: `finwise-accounting/frontend/src/components/AppLayout.vue`
- Create: `finwise-accounting/frontend/src/views/BankLedgerView.vue`
- Create: `finwise-accounting/frontend/src/views/InvoiceLedgerView.vue`
- Create: `finwise-accounting/frontend/src/views/SourceLedgerView.spec.js`

- [ ] **Step 1: Write source-level frontend tests**

Assert routes, API endpoints, scroll wrappers, Chinese labels, and no raw enum display:

```js
expect(clientSource).toContain('/monthly-packages/${packageId}/bank-ledger')
expect(clientSource).toContain('/monthly-packages/${packageId}/invoice-ledger')
expect(routerSource).toContain('/bank-ledger')
expect(routerSource).toContain('/invoice-ledger')
expect(bankViewSource).toContain('资金流水')
expect(invoiceViewSource).toContain('发票台账')
expect(bankViewSource).toContain('ledger-table-scroll')
expect(invoiceViewSource).toContain('ledger-table-scroll')
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run test -- SourceLedgerView.spec.js
```

Expected: fail because pages do not exist.

- [ ] **Step 3: Add API client methods**

Add:

```js
sourceLedgers: {
  bank: (packageId) => apiClient.get(`/monthly-packages/${packageId}/bank-ledger`),
  invoices: (packageId) => apiClient.get(`/monthly-packages/${packageId}/invoice-ledger`),
  summary: (packageId) => apiClient.get(`/monthly-packages/${packageId}/voucher-ledger-summary`),
}
```

- [ ] **Step 4: Add routes and navigation**

Add routes:

- `/bank-ledger` -> `BankLedgerView`
- `/invoice-ledger` -> `InvoiceLedgerView`

Add navigation labels:

- `资金流水`
- `发票台账`

- [ ] **Step 5: Build pages**

Both pages must:

- Use `PackageContextBar` or the existing package selection pattern.
- Load active package data.
- Provide search input.
- Provide Chinese status tags.
- Wrap tables in `ledger-table-scroll`.
- Keep action columns visible via horizontal scroll at narrow widths.

- [ ] **Step 6: Run frontend tests**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run test -- SourceLedgerView.spec.js
```

Expected: pass.

### Task 4: Voucher Workbench Task Summary And Full-Coverage UX

**Files:**
- Modify: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.vue`
- Modify: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.spec.js`

- [ ] **Step 1: Write failing frontend tests**

Add assertions for:

- `当月整理摘要`
- `完全配对`
- `差额补齐`
- `单边补齐`
- `历史延续`
- `api.sourceLedgers.summary`
- explicit click handlers without raw DOM event payloads

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run test -- VoucherWorkbenchView.spec.js
```

Expected: fail until summary UI is added.

- [ ] **Step 3: Add summary panel**

Show:

- 银行流水处理进度
- 发票处理进度
- 凭证任务总数
- 待确认任务
- 差额合计
- 单边暂挂合计

- [ ] **Step 4: Add task type filters**

Filters:

- 全部
- 完全配对
- 差额补齐
- 单边补齐
- 历史延续
- 待确认
- 已确认
- 异常

- [ ] **Step 5: Add task type labels in voucher list**

Render source group/task type with Chinese labels:

```js
const taskTypeLabels = {
  FULL_MATCH: '完全配对',
  DIFFERENCE_COMPLETION: '差额补齐',
  SINGLE_SOURCE: '单边补齐',
  HISTORICAL_REVIEW: '历史延续',
}
```

- [ ] **Step 6: Run frontend tests**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run test -- VoucherWorkbenchView.spec.js
```

Expected: pass.

### Task 5: Rule Memory Persistence For User Edits

**Files:**
- Modify: `finwise-accounting/backend/app/services/voucher_service.py`
- Test: `finwise-accounting/backend/tests/test_voucher_service.py`
- Modify: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.vue`

- [ ] **Step 1: Write failing rule-memory test**

Confirming a modified treatment should create or update a `VoucherRule`:

```python
def test_adjusting_single_source_treatment_records_voucher_rule(db_session):
    voucher = create_bank_only_voucher(db_session)
    update_single_source_voucher_treatment(
        db_session,
        voucher_id=voucher.id,
        treatment_type="预收账款暂挂",
        summary="记录银行收款待补发票",
        debit_account_code="1002",
        credit_account_code="2203",
        note="客户确认按预收处理",
    )
    rules = db_session.scalars(select(VoucherRule).where(VoucherRule.enterprise_id == voucher_enterprise_id)).all()
    assert rules
    assert rules[0].credit_account_code == "2203"
```

- [ ] **Step 2: Run failing test**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest tests/test_voucher_service.py::test_adjusting_single_source_treatment_records_voucher_rule -q
```

Expected: fail until rule creation is added.

- [ ] **Step 3: Add rule upsert helper**

Implement `_record_voucher_rule_from_user_edit()` that upserts by enterprise, counterparty, direction, and treatment type.

- [ ] **Step 4: Call helper from treatment adjustment and rematch**

Persist user edits after:

- `update_single_source_voucher_treatment()`
- `rematch_voucher()`
- `confirm_voucher()` when source data contains user-edited treatment metadata

- [ ] **Step 5: Run backend tests**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest tests/test_voucher_service.py -q
```

Expected: pass.

### Task 6: Audit, Browser Verification, And Cleanup

**Files:**
- Test/audit only unless bugs are found.

- [ ] **Step 1: Run full backend tests**

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest -q
```

Expected: pass.

- [ ] **Step 2: Run full frontend tests and build**

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run test -- --run
npm run build
```

Expected: pass.

- [ ] **Step 3: Restart services**

```bash
tmux kill-session -t finwise-backend 2>/dev/null || true
tmux new-session -d -s finwise-backend 'cd /Users/starryn/project/finwise/finwise-accounting/backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8001'
tmux kill-session -t finwise-frontend 2>/dev/null || true
tmux new-session -d -s finwise-frontend 'cd /Users/starryn/project/finwise/finwise-accounting/frontend && npm run dev -- --host 127.0.0.1 --port 5174'
```

- [ ] **Step 4: Browser flow verification**

Use the browser against `http://127.0.0.1:5174`:

1. Select 昆山黛珂特电子科技有限公司 and 2026-04.
2. Open `资金流水`, verify 141 rows or imported count and visible statuses.
3. Open `发票台账`, verify invoice rows and direction-specific counterparties.
4. Open `凭证管理`, click `生成草稿并 AI 推荐`.
5. Verify summary counts cover all bank/invoice sources.
6. Search a known counterparty.
7. Open a single-source task, adjust treatment, save, refresh, verify retained.
8. Open rematch dialog, search candidates, verify hover details and disabled confirmed rows.
9. Confirm a voucher and verify voucher number.
10. Narrow viewport and verify table action columns remain reachable.

- [ ] **Step 5: Cleanup test data if created by browser verification**

If verification creates temporary vouchers or rules in the development DB, remove only the test artifacts created during this run. Do not delete imported source data unless explicitly requested.

- [ ] **Step 6: Final audit note**

Report:

- Tests run
- Browser flows verified
- Known limitations
- Files changed
