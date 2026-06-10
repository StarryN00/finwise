# Voucher Composite Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete voucher generation for one-to-many, many-to-one, and one-sided bank/invoice sources.

**Architecture:** Keep the existing `MatchRecord` one-bank/one-invoice table for pair suggestions, and add combination behavior in voucher generation using `Voucher.source_key` and `Voucher.source_data`. This avoids a schema migration while letting the voucher layer represent grouped sources.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, Vue 3, Element Plus, Vitest.

---

### Task 1: Backend source coverage tests

**Files:**
- Modify: `finwise-accounting/backend/tests/test_voucher_service.py`

- [ ] Add tests for multi-bank single-invoice, single-bank multi-invoice, and one-sided bank voucher account defaults.
- [ ] Run targeted tests and verify the new tests fail before production code changes.

### Task 2: Backend voucher generation

**Files:**
- Modify: `finwise-accounting/backend/app/accounting/subjects.py`
- Modify: `finwise-accounting/backend/app/services/voucher_service.py`

- [ ] Add small-business subjects `1123 预付账款`, `1221 其他应收款`, `2203 预收账款`, `2241 其他应付款`.
- [ ] Add grouping helpers that build vouchers from amount-balanced one-to-many and many-to-one candidate groups.
- [ ] Adjust bank-only vouchers to use prepayment/advance receipts instead of direct expense/receivable defaults.
- [ ] Keep existing one-to-one and bank-fee behavior stable.

### Task 3: Frontend workbench support

**Files:**
- Modify: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.vue`
- Modify: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.spec.js`

- [ ] Render source arrays in voucher details.
- [ ] Show single-source pending vouchers as “待补发票/待确认归属”.
- [ ] Ensure rematch candidate UI still scrolls and can expose multi-source flow affordances.

### Task 4: Verification

**Commands:**
- `cd finwise-accounting/backend && uv run pytest tests/test_voucher_service.py tests/test_voucher_api.py -q`
- `cd finwise-accounting/backend && uv run pytest -q`
- `cd finwise-accounting/frontend && npm test -- --run`
- `cd finwise-accounting/frontend && npm run build`

### Task 5: Real data smoke test

**Flow:**
- Generate vouchers for 昆山黛珂特电子科技有限公司 2026-04.
- Refresh `http://127.0.0.1:5174/vouchers`.
- Confirm the page reports the larger voucher count and details show single-sided and grouped sources.
