# Merged Account Details Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace split bank/invoice account detail rows with a merged business-record view that shows counterparties, invoice parties, remarks, completeness, and manual confirmation state.

**Architecture:** Keep the existing `/api/workspace` response as the data source and reshape `accountRows` in `workspace_service.py`. The frontend continues to consume `workspace.accountRows`, but `AccountDetailsView.vue` becomes a unified table with filters instead of separate bank and invoice tabs.

**Tech Stack:** FastAPI service layer, SQLAlchemy models, Vue 3 Composition API, Element Plus table and filters, Vitest source assertions, pytest API assertions.

---

### Task 1: Backend Merged Account Rows

**Files:**
- Modify: `finwise-accounting/backend/app/services/workspace_service.py`
- Modify: `finwise-accounting/backend/tests/test_matching_workflow_api.py`

- [ ] **Step 1: Write failing API test**

Add a test that creates one confirmed bank-invoice match, one unmatched bank transaction, and one unmatched invoice. Assert `/api/workspace` returns:
- one merged row for the match with `sourceCompleteness == "流水+发票"`
- `payer`, `payee`, `seller`, `buyer`, and `remark`
- one bank-only row with `sourceCompleteness == "缺失发票主体"`
- one invoice-only row with `sourceCompleteness == "缺失转账主体"`

- [ ] **Step 2: Run focused test**

Run: `cd finwise-accounting/backend && python3 -m pytest tests/test_matching_workflow_api.py::test_workspace_rows_merge_bank_and_invoice_sources -q`

Expected: fails because rows are still split and fields are missing.

- [ ] **Step 3: Implement merged row builder**

Change `_account_rows()` so it first emits rows for matched records, then emits unmatched bank rows, unmatched invoice rows, and existing accounting lines. Use helper functions for bank direction and invoice parties.

- [ ] **Step 4: Run focused and regression tests**

Run:
- `cd finwise-accounting/backend && python3 -m pytest tests/test_matching_workflow_api.py -q`
- `cd finwise-accounting/backend && python3 -m pytest -q`

Expected: all tests pass.

### Task 2: Frontend Unified Details View

**Files:**
- Modify: `finwise-accounting/frontend/src/views/AccountDetailsView.vue`
- Create: `finwise-accounting/frontend/src/views/AccountDetailsView.spec.js`

- [ ] **Step 1: Write failing source test**

Assert `AccountDetailsView.vue` contains unified filter labels, new party columns, `sourceCompleteness`, and no split tab labels.

- [ ] **Step 2: Run focused frontend test**

Run: `cd finwise-accounting/frontend && npm test -- AccountDetailsView.spec.js`

Expected: fails until the table is changed.

- [ ] **Step 3: Implement unified table**

Replace the tabs with a segmented filter for `全部 / 待确认 / 缺失发票 / 缺失转账 / 已完整`. Add columns for `payer`, `payee`, `seller`, `buyer`, `remark`, and `sourceCompleteness`.

- [ ] **Step 4: Run frontend tests and build**

Run:
- `cd finwise-accounting/frontend && npm test`
- `cd finwise-accounting/frontend && npm run build`

Expected: tests and build pass.

### Task 3: Browser Verification and Commit

**Files:**
- Verify local app at `http://127.0.0.1:5174/account-details`

- [ ] **Step 1: Restart backend if needed**

Restart `uvicorn` on port `8001` so `/api/workspace` uses the new code.

- [ ] **Step 2: Browser check**

Open `/account-details` and verify the unified table shows the new columns and filters.

- [ ] **Step 3: Cleanup and commit**

Remove generated `frontend/dist` and `.playwright-cli` artifacts, run `git diff --check -- finwise-accounting`, then commit only `finwise-accounting/` files and this plan.
