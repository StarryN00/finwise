# Auxiliary Trial Balance Upgrade Plan

> **For StarryN:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan.

**Goal:** Upgrade FinWise ledger output so the balance table supports account-level parent rows plus auxiliary accounting child rows, closer to the EasyAccounting-style balance sheet. Preserve existing confirmed-voucher-only ledger behavior.

## Scope

1. Add trial-balance row metadata:
   - account parent row vs auxiliary child row
   - parent account code
   - auxiliary type/name/code
   - display code/name, level, expandable flag
2. Use imported historical balance rows as opening balances where available.
3. Derive current-period auxiliary rows from confirmed voucher source data:
   - bank deposit rows can use bank account information when available
   - receivable/payable/current-account rows use counterparty information from invoice/bank source data
4. Update the frontend ledger balance view:
   - separate columns for subject code and subject name
   - parent account rows visually distinct
   - auxiliary rows indented under parent accounts
   - keep dense-table scroll behavior
5. Add regression tests for:
   - opening balances from historical import
   - auxiliary child rows under trial balance
   - frontend balance-table structure and styling hooks

## Out of Scope

- No database migration for voucher-entry auxiliary columns in this pass.
- No backend pagination changes for ledger tables.
- No automatic month-end carry-forward yet.
- No manual auxiliary subject creation UI yet.

## Implementation Steps

1. Write failing backend tests in `backend/tests/test_ledger_service.py`.
2. Extend `backend/app/schemas/ledger.py` with row metadata fields.
3. Update `backend/app/services/ledger_service.py`:
   - load package enterprise/year
   - aggregate historical opening balances
   - build parent rows from opening + confirmed current-period vouchers
   - build auxiliary child rows from confirmed current-period vouchers
   - calculate trial-balance totals from parent rows only
4. Write/update frontend tests in `frontend/src/views/LedgerView.spec.js`.
5. Update `frontend/src/views/LedgerView.vue` balance-table columns and row classes.
6. Run targeted backend and frontend tests.
7. Run a browser check on `/ledgers` or the ledger route available in the app, focusing on the balance table.

## Acceptance Criteria

- Trial balance parent rows still balance by debit/credit totals.
- Imported historical opening balance is reflected in parent rows.
- Auxiliary rows appear under relevant accounts without double-counting totals.
- Frontend shows `科目编码` and `科目名称` instead of a single combined subject label.
- Auxiliary rows are visibly indented and parent rows are distinguishable.
- Existing journal/general/detail tests remain passing.
