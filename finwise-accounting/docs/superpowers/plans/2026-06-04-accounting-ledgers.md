# Accounting Ledgers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FinWise ledger module that derives 序时账、总账、明细账、余额表 from confirmed monthly vouchers.

**Architecture:** Add a backend ledger service that reads confirmed vouchers and computes ledger rows in memory. Add package-based ledger API endpoints and a Vue 3 `/ledgers` page with tabs, filters, pagination, and Chinese labels.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, pytest, Vue 3, Element Plus, Vitest.

---

## File Structure

- Create `finwise-accounting/backend/app/schemas/ledger.py`: Pydantic response schemas for summary, journal, general ledger, detail ledger, and trial balance.
- Create `finwise-accounting/backend/app/services/ledger_service.py`: Pure ledger calculation service over confirmed vouchers.
- Create `finwise-accounting/backend/app/api/ledgers.py`: Package-based API routes.
- Modify `finwise-accounting/backend/app/main.py`: Register ledger router.
- Create `finwise-accounting/backend/tests/test_ledger_service.py`: Backend service unit tests.
- Create `finwise-accounting/backend/tests/test_ledger_api.py`: API route tests.
- Create `finwise-accounting/frontend/src/views/LedgerView.vue`: Ledger page.
- Create `finwise-accounting/frontend/src/views/LedgerView.spec.js`: Frontend page tests.
- Modify `finwise-accounting/frontend/src/router/index.js`: Add `/ledgers` route.
- Modify `finwise-accounting/frontend/src/components/AppLayout.vue`: Add `账簿` navigation entry.
- Modify `finwise-accounting/frontend/src/api/client.js`: Add ledger API helpers.
- Modify `finwise-accounting/frontend/src/api/client.spec.js`: Assert ledger endpoints.
- Modify `finwise-accounting/frontend/src/components/AppLayout.spec.js`: Assert nav label.

## Task 1: Backend Ledger Service Tests

**Files:**
- Create: `finwise-accounting/backend/tests/test_ledger_service.py`

- [ ] **Step 1: Write service tests**

Create tests covering confirmed-only filtering, journal sorting, subject grouping, detail running balances, and trial-balance totals.

```python
from __future__ import annotations

from decimal import Decimal

from app.models.entities import (
    MonthlyWorkPackage,
    Organization,
    Voucher,
    VoucherEntry,
)
from app.services.ledger_service import LedgerService


def money(value: str) -> Decimal:
    return Decimal(value)


def seed_package(db):
    org = Organization(name="默认组织")
    db.add(org)
    db.flush()
    package = MonthlyWorkPackage(
        organization_id=org.id,
        enterprise_id="11111111-1111-1111-1111-111111111111",
        period_year=2026,
        period_month=4,
        status="MATCHED",
    )
    db.add(package)
    db.flush()
    return package


def add_voucher(db, package, number, date, status, entries):
    voucher = Voucher(
        organization_id=package.organization_id,
        monthly_work_package_id=package.id,
        voucher_date=date,
        voucher_number=number,
        summary=f"摘要{number}",
        source_data={},
        ai_confidence=90,
        status=status,
    )
    db.add(voucher)
    db.flush()
    for direction, account_code, account_name, amount in entries:
        db.add(
            VoucherEntry(
                voucher_id=voucher.id,
                direction=direction,
                account_code=account_code,
                account_name=account_name,
                amount=money(amount),
                source_type="manual",
                source_id=str(voucher.id),
            )
        )
    db.flush()
    return voucher


def test_journal_uses_only_confirmed_vouchers_and_sorts_rows(db_session):
    package = seed_package(db_session)
    add_voucher(
        db_session,
        package,
        "记-0002",
        "2026-04-02",
        "CONFIRMED",
        [("DEBIT", "1002", "银行存款", "200.00"), ("CREDIT", "5001", "主营业务收入", "200.00")],
    )
    add_voucher(
        db_session,
        package,
        "记-0001",
        "2026-04-01",
        "CONFIRMED",
        [("DEBIT", "560203", "服务费", "100.00"), ("CREDIT", "1002", "银行存款", "100.00")],
    )
    add_voucher(
        db_session,
        package,
        None,
        "2026-04-03",
        "PENDING_CONFIRMATION",
        [("DEBIT", "560203", "服务费", "300.00"), ("CREDIT", "1002", "银行存款", "300.00")],
    )

    rows = LedgerService(db_session).get_journal(package.id)

    assert [row.voucher_number for row in rows] == ["记-0001", "记-0001", "记-0002", "记-0002"]
    assert rows[0].account_code == "560203"
    assert rows[0].debit_amount == money("100.00")
    assert rows[1].credit_amount == money("100.00")


def test_general_ledger_groups_current_period_amounts(db_session):
    package = seed_package(db_session)
    add_voucher(
        db_session,
        package,
        "记-0001",
        "2026-04-01",
        "CONFIRMED",
        [("DEBIT", "1002", "银行存款", "200.00"), ("CREDIT", "5001", "主营业务收入", "200.00")],
    )
    add_voucher(
        db_session,
        package,
        "记-0002",
        "2026-04-02",
        "CONFIRMED",
        [("DEBIT", "560203", "服务费", "50.00"), ("CREDIT", "1002", "银行存款", "50.00")],
    )

    rows = {row.account_code: row for row in LedgerService(db_session).get_general(package.id)}

    assert rows["1002"].period_debit == money("200.00")
    assert rows["1002"].period_credit == money("50.00")
    assert rows["1002"].closing_debit == money("150.00")
    assert rows["5001"].closing_credit == money("200.00")
    assert rows["560203"].closing_debit == money("50.00")


def test_detail_ledger_calculates_running_balance_and_counter_accounts(db_session):
    package = seed_package(db_session)
    add_voucher(
        db_session,
        package,
        "记-0001",
        "2026-04-01",
        "CONFIRMED",
        [("DEBIT", "1002", "银行存款", "200.00"), ("CREDIT", "5001", "主营业务收入", "200.00")],
    )
    add_voucher(
        db_session,
        package,
        "记-0002",
        "2026-04-02",
        "CONFIRMED",
        [("DEBIT", "560203", "服务费", "50.00"), ("CREDIT", "1002", "银行存款", "50.00")],
    )

    rows = LedgerService(db_session).get_detail(package.id, "1002")

    assert rows[0].balance == money("200.00")
    assert rows[0].counter_accounts == "主营业务收入"
    assert rows[1].balance == money("150.00")
    assert rows[1].counter_accounts == "服务费"


def test_trial_balance_returns_balanced_totals(db_session):
    package = seed_package(db_session)
    add_voucher(
        db_session,
        package,
        "记-0001",
        "2026-04-01",
        "CONFIRMED",
        [("DEBIT", "1002", "银行存款", "200.00"), ("CREDIT", "5001", "主营业务收入", "200.00")],
    )

    result = LedgerService(db_session).get_trial_balance(package.id)

    assert result.is_balanced is True
    assert result.period_debit_total == money("200.00")
    assert result.period_credit_total == money("200.00")
    assert result.difference == money("0.00")
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd finwise-accounting/backend
pytest tests/test_ledger_service.py -q
```

Expected: fail because `app.services.ledger_service` does not exist.

## Task 2: Backend Ledger Service Implementation

**Files:**
- Create: `finwise-accounting/backend/app/schemas/ledger.py`
- Create: `finwise-accounting/backend/app/services/ledger_service.py`

- [ ] **Step 1: Implement schemas**

Implement Pydantic models with `Decimal` fields for all ledger values.

- [ ] **Step 2: Implement service**

Implement `LedgerService` methods:

- `get_summary(package_id)`
- `get_journal(package_id)`
- `get_general(package_id)`
- `get_detail(package_id, account_code)`
- `get_trial_balance(package_id)`

Rules:

- Query only vouchers where `monthly_work_package_id == package_id` and `status == "CONFIRMED"`.
- Sort by `voucher_date`, `voucher_number`, `VoucherEntry.id`.
- For normal balance, use the first digit of `account_code`:
  - `1`, `4`, `5`: debit
  - `2`, `3`, `6`: credit
  - default: debit
- Quantize all money to 2 decimals.

- [ ] **Step 3: Run service tests and verify GREEN**

Run:

```bash
cd finwise-accounting/backend
pytest tests/test_ledger_service.py -q
```

Expected: all tests pass.

## Task 3: Backend API Tests And Routes

**Files:**
- Create: `finwise-accounting/backend/tests/test_ledger_api.py`
- Create: `finwise-accounting/backend/app/api/ledgers.py`
- Modify: `finwise-accounting/backend/app/main.py`

- [ ] **Step 1: Write failing API tests**

Tests should call:

- `/api/monthly-packages/{package_id}/ledgers/summary`
- `/api/monthly-packages/{package_id}/ledgers/journal`
- `/api/monthly-packages/{package_id}/ledgers/general`
- `/api/monthly-packages/{package_id}/ledgers/detail?account_code=1002`
- `/api/monthly-packages/{package_id}/ledgers/trial-balance`

Assert 200 responses and expected Chinese-facing values.

- [ ] **Step 2: Run API tests and verify RED**

Run:

```bash
cd finwise-accounting/backend
pytest tests/test_ledger_api.py -q
```

Expected: fail with 404 or missing router.

- [ ] **Step 3: Implement API routes**

Create `app.api.ledgers.router` with prefix `/api/monthly-packages/{package_id}/ledgers`.

- [ ] **Step 4: Register router and verify GREEN**

Run:

```bash
cd finwise-accounting/backend
pytest tests/test_ledger_api.py tests/test_ledger_service.py -q
```

Expected: all ledger backend tests pass.

## Task 4: Frontend API And Navigation Tests

**Files:**
- Modify: `finwise-accounting/frontend/src/api/client.js`
- Modify: `finwise-accounting/frontend/src/api/client.spec.js`
- Modify: `finwise-accounting/frontend/src/router/index.js`
- Modify: `finwise-accounting/frontend/src/components/AppLayout.vue`
- Modify: `finwise-accounting/frontend/src/components/AppLayout.spec.js`

- [ ] **Step 1: Write failing frontend tests**

Assert:

- `api.ledgers.summary(packageId)` calls `/api/monthly-packages/{packageId}/ledgers/summary`
- `api.ledgers.journal(packageId)` calls `/api/monthly-packages/{packageId}/ledgers/journal`
- `api.ledgers.general(packageId)` calls `/api/monthly-packages/{packageId}/ledgers/general`
- `api.ledgers.detail(packageId, accountCode)` calls `/api/monthly-packages/{packageId}/ledgers/detail?account_code={accountCode}`
- `api.ledgers.trialBalance(packageId)` calls `/api/monthly-packages/{packageId}/ledgers/trial-balance`
- Layout nav contains `账簿`
- Router contains `/ledgers`

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd finwise-accounting/frontend
npm test -- src/api/client.spec.js src/components/AppLayout.spec.js --run
```

Expected: fail because ledger API and nav do not exist.

- [ ] **Step 3: Implement minimal frontend API/nav/router**

Add ledger helpers, route, and nav item.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
cd finwise-accounting/frontend
npm test -- src/api/client.spec.js src/components/AppLayout.spec.js --run
```

Expected: targeted tests pass.

## Task 5: Ledger Page Tests And Implementation

**Files:**
- Create: `finwise-accounting/frontend/src/views/LedgerView.vue`
- Create: `finwise-accounting/frontend/src/views/LedgerView.spec.js`

- [ ] **Step 1: Write failing page tests**

Assert:

- Page title is `账簿`
- Default tab is `序时账`
- Table defaults to 20 rows per page
- Pagination summary uses `当前显示 X 条 / 筛选结果 Y 条 / 原始总数 Z 条`
- Switching to `总账` calls general ledger API
- Switching to `明细账` shows account selector and calls detail API
- Switching to `余额表` calls trial-balance API
- Search resets current page to 1
- Pending voucher count displays a warning when nonzero
- No raw enum values such as `DEBIT`, `CREDIT`, `CONFIRMED` are visible

- [ ] **Step 2: Run page tests and verify RED**

Run:

```bash
cd finwise-accounting/frontend
npm test -- src/views/LedgerView.spec.js --run
```

Expected: fail because `LedgerView.vue` does not exist or behavior is missing.

- [ ] **Step 3: Implement LedgerView**

Use Element Plus:

- `el-tabs`
- `el-table`
- `el-pagination`
- enterprise and period selectors following existing workbench pages
- `show-overflow-tooltip` on long text columns
- compact amount/date/status columns

All table wrappers must fill available width and avoid clipped overflow.

- [ ] **Step 4: Run page tests and verify GREEN**

Run:

```bash
cd finwise-accounting/frontend
npm test -- src/views/LedgerView.spec.js --run
```

Expected: page tests pass.

## Task 6: Full Verification

**Files:**
- No planned file changes unless verification exposes defects.

- [ ] **Step 1: Run backend ledger and voucher tests**

Run:

```bash
cd finwise-accounting/backend
pytest tests/test_ledger_service.py tests/test_ledger_api.py tests/test_voucher_api.py tests/test_voucher_service.py -q
```

Expected: pass.

- [ ] **Step 2: Run frontend targeted tests**

Run:

```bash
cd finwise-accounting/frontend
npm test -- src/views/LedgerView.spec.js src/api/client.spec.js src/components/AppLayout.spec.js --run
```

Expected: pass.

- [ ] **Step 3: Build frontend**

Run:

```bash
cd finwise-accounting/frontend
npm run build
```

Expected: build succeeds.

- [ ] **Step 4: Browser verification**

Open `http://127.0.0.1:5174/ledgers` and verify:

- `账簿` nav item is visible.
- Enterprise and period selectors work.
- 序时账 displays confirmed voucher entries.
- 总账 displays subject summaries.
- 明细账 account selector changes rows.
- 余额表 displays balance totals and balanced state.
- Search and pagination work.
- No raw backend enum values are visible.
