# Single-Sided Voucher Treatment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators see and adjust the suggested accounting treatment directly in the missing source panel for bank-only or invoice-only vouchers.

**Architecture:** Keep source matching separate from accounting treatment. Backend adds one narrow endpoint that rebuilds entries for a single-sided voucher with selected debit/credit subjects and audit log. Frontend renders a missing-source treatment card in the existing source grid and exposes an inline adjustment form.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, Vue 3, Element Plus, Vitest.

---

### Task 1: Backend adjustment contract

**Files:**
- Modify: `finwise-accounting/backend/app/schemas/voucher.py`
- Modify: `finwise-accounting/backend/app/api/vouchers.py`
- Modify: `finwise-accounting/backend/app/services/voucher_service.py`
- Test: `finwise-accounting/backend/tests/test_voucher_api.py`

- [ ] Add failing API test: single bank receipt voucher can be adjusted from default 2203 to 2241 with note, keeps status pending, updates source_data treatment, and validates entries.
- [ ] Implement `VoucherTreatmentAdjustmentRequest` and endpoint `POST /api/vouchers/{voucher_id}/treatment-adjustment`.
- [ ] Implement service function that only allows single-sided vouchers, validates account subjects, replaces entries, updates summary/ai_reason/source_data, writes audit log.
- [ ] Run targeted voucher API tests.

### Task 2: Frontend missing-source treatment card

**Files:**
- Modify: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.vue`
- Modify: `finwise-accounting/frontend/src/api/client.js`
- Test: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.spec.js`

- [ ] Add failing source test requiring missing-source card labels, treatment form state, and API client method.
- [ ] Render missing invoice/bank card when source data is single-sided.
- [ ] Add inline treatment form with treatment type, debit subject, credit subject, summary, note.
- [ ] Submit to backend and refresh voucher detail.
- [ ] Run frontend tests and build.

### Task 3: Verification

- [ ] Run backend voucher tests and backend full test suite.
- [ ] Run frontend full test suite and build.
- [ ] Restart backend service.
- [ ] Browser verify: open a bank-only receipt voucher, see missing invoice treatment card, open adjustment form, confirm controls are visible.
