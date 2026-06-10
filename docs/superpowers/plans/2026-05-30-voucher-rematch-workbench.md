# Voucher Rematch Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow operators to reject an incorrect voucher draft, choose the correct bank transaction or invoice candidate, and rebuild the voucher draft without losing audit history.

**Architecture:** Add two focused voucher APIs: one to list rematch candidates for the selected voucher, and one to apply a manual rematch. The backend owns validation, candidate scoring, match record creation, voucher source data, and entry rebuilding. The frontend exposes this through a detail-side “重新匹配” dialog shown for pending or rejected vouchers.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Vue 3, Element Plus, Vitest, pytest, Playwright.

---

### Task 1: Backend Rematch API

**Files:**
- Modify: `finwise-accounting/backend/app/schemas/voucher.py`
- Modify: `finwise-accounting/backend/app/services/voucher_service.py`
- Modify: `finwise-accounting/backend/app/api/vouchers.py`
- Test: `finwise-accounting/backend/tests/test_voucher_api.py`

- [ ] Add failing API test `test_rematch_voucher_api_lists_candidates_and_rebuilds_draft` that creates a wrong voucher from one invoice, creates another candidate invoice with the same total amount, calls `/api/vouchers/{id}/rematch-candidates`, then calls `/api/vouchers/{id}/rematch` and asserts the returned voucher uses the new invoice and remains `PENDING_CONFIRMATION`.
- [ ] Add schemas `VoucherRematchCandidateRead`, `VoucherRematchCandidatesResponse`, and `VoucherRematchRequest`.
- [ ] Add service functions `list_voucher_rematch_candidates` and `rematch_voucher`.
- [ ] Candidate selection must score exact amount, date proximity, and counterparty overlap; exclude sources already used by non-rejected vouchers.
- [ ] Rematch must create a new manual match record, rebuild source data and entries, clear rejection validation errors, clear voucher number, and leave the voucher pending for human confirmation.
- [ ] Add routes `GET /api/vouchers/{voucher_id}/rematch-candidates` and `POST /api/vouchers/{voucher_id}/rematch`.
- [ ] Run targeted backend voucher API/service tests.

### Task 2: Frontend Rematch Dialog

**Files:**
- Modify: `finwise-accounting/frontend/src/api/client.js`
- Modify: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.vue`
- Test: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.spec.js`

- [ ] Add failing source test assertions for `重新匹配`, `rematchDialogVisible`, `api.vouchers.rematchCandidates`, and `api.vouchers.rematch`.
- [ ] Add API client methods for rematch candidate fetch and rematch apply.
- [ ] Add a detail-side “重新匹配” button for pending/rejected vouchers.
- [ ] Add an Element Plus dialog with invoice candidates and bank candidates. The operator can select one candidate and click “应用重新匹配”.
- [ ] After rematch, reload workspace and voucher list, keep the rebuilt voucher selected, and show visible success feedback.
- [ ] Run frontend unit tests and build.

### Task 3: Browser Verification

**Files:**
- No source files unless verification finds a defect.

- [ ] Restart backend so the new routes are live.
- [ ] Use browser automation on `http://127.0.0.1:5174/vouchers`.
- [ ] Select `昆山黛珂特电子科技有限公司 / 2026-04`.
- [ ] Open a voucher detail and verify `重新匹配` is visible.
- [ ] Open the dialog and verify candidates load.
- [ ] Apply one rematch only if using a controlled disposable/test voucher; do not alter important real business vouchers without explicit user request.
- [ ] Verify final UI state and API responses.
