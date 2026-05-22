# Phase 1 Audit

## Verification

- Backend end-to-end flow: `python3 -m pytest tests/test_end_to_end_monthly_flow.py -q` -> 1 passed.
- Backend tests: `python3 -m pytest -q` -> 67 passed.
- Frontend build: `npm run build` -> passed. Vite reports an Element Plus bundle-size warning; no build errors.
- Backend health: `curl http://127.0.0.1:8001/health` -> `{"status":"ok"}`.
- Browser check: Playwright snapshots verified enterprise list, monthly workspace, account detail tabs, and output center on `http://127.0.0.1:5174`.

## Privacy

- AI payloads exclude enterprise names: covered by `tests/test_reports_and_privacy.py`.
- AI payloads exclude tax numbers: covered by `tests/test_reports_and_privacy.py`.
- Counterparty names are masked: covered by `tests/test_reports_and_privacy.py`; company names are reduced to first two Chinese characters plus `***公司`.

## Scope

- Old backend/frontend untouched by rebuild commits: `git diff --name-only 2935e4b..HEAD -- backend frontend` returned no files.
- Current working tree still contains pre-existing root `backend/` and `frontend/` dirty files from outside this rebuild; they were not staged or committed by the rebuild.
- No direct tax bureau submission: Phase 1 only generates VAT draft data and Excel export.
- No full voucher/general ledger replacement: Phase 1 generates matching records, accounting lines, estimated statements, filing drafts, and reports.

## Remaining Risks

- PDF bank statement parsing: not implemented; current import path supports structured CSV/XLS/XLSX rows.
- Exact Jiangsu electronic tax bureau import compatibility: Excel export is copyable draft format, not an official tax bureau upload template.
- More bank and invoice templates: current aliases cover common fields; production should expand with real Suzhou agency samples.
- Frontend data binding: Task 9 uses a real API client but mock Pinia data for page scaffolding; production wiring remains separate.
