# Smart Voucher Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first delivered version of the FinWise smart voucher workbench: small-business accounting subject initialization/listing, voucher draft generation from confirmed bank/invoice matches, deterministic validation, manual confirmation, and Vue navigation/workbench pages.

**Architecture:** Keep vouchers as a monthly work package output, downstream of current imports and matching. Add focused backend models and services for account subjects, reserved voucher rule metadata, voucher drafts, and voucher entries; expose subject initialization/listing plus voucher generation/listing/confirmation through a new `vouchers` API router. Add two frontend views: read-only subject settings and voucher workbench confirmation, while preserving the existing account details and matching behavior. Rule memory, subject edit controls, and reject controls are reserved or deferred follow-ups, not part of this first implementation.

**Tech Stack:** FastAPI, SQLAlchemy ORM, SQLite/PostgreSQL-compatible models, pytest, Vue 3, Pinia, Element Plus, Vitest source-level tests.

---

## File Structure

- Create `finwise-accounting/backend/app/accounting/subjects.py`: built-in small-business accounting subject template and helper functions.
- Create `finwise-accounting/backend/app/services/voucher_service.py`: account subject initialization/listing, voucher generation, validation, and confirmation.
- Create `finwise-accounting/backend/app/schemas/voucher.py`: request/response schemas for subjects, vouchers, entries, generation, and confirmation.
- Create `finwise-accounting/backend/app/api/vouchers.py`: REST endpoints under `/api/enterprises/{enterprise_id}/account-subjects` and `/api/monthly-packages/{package_id}/vouchers`.
- Modify `finwise-accounting/backend/app/models/entities.py`: add `AccountSubject`, `VoucherRule`, `Voucher`, and `VoucherEntry`.
- Modify `finwise-accounting/backend/app/models/__init__.py`: export new models.
- Modify `finwise-accounting/backend/app/main.py`: include voucher router and add SQLite startup indexes/columns if needed.
- Modify `finwise-accounting/frontend/src/api/client.js`: add `accountSubjects` and `vouchers` API clients.
- Modify `finwise-accounting/frontend/src/router/index.js`: add `/account-subjects` and `/vouchers` routes.
- Create `finwise-accounting/frontend/src/views/AccountSubjectsView.vue`: enterprise subject table and initialization control.
- Create `finwise-accounting/frontend/src/views/VoucherWorkbenchView.vue`: generation toolbar, filters, voucher list, detail panel, and confirm control.
- Modify `finwise-accounting/frontend/src/views/WorkspaceHomeView.vue` or the app navigation component if needed to surface the new pages.
- Create `finwise-accounting/backend/tests/test_voucher_service.py`: service-level generation and validation tests.
- Create `finwise-accounting/backend/tests/test_voucher_api.py`: API lifecycle tests.
- Create `finwise-accounting/frontend/src/views/VoucherWorkbenchView.spec.js`: source-level UI contract tests.
- Create `finwise-accounting/frontend/src/views/AccountSubjectsView.spec.js`: source-level UI contract tests.

---

## Task 1: Accounting Subject Model And Template

**Files:**
- Modify: `finwise-accounting/backend/app/models/entities.py`
- Modify: `finwise-accounting/backend/app/models/__init__.py`
- Create: `finwise-accounting/backend/app/accounting/subjects.py`
- Test: `finwise-accounting/backend/tests/test_voucher_service.py`

- [ ] **Step 1: Write the failing subject initialization test**

Add this test skeleton to `finwise-accounting/backend/tests/test_voucher_service.py`:

```python
from uuid import UUID

from app.models import Enterprise
from app.services.voucher_service import ensure_enterprise_subjects


ORG = UUID("00000000-0000-0000-0000-000000000001")


def make_enterprise(db_session):
    enterprise = Enterprise(
        organization_id=ORG,
        name="苏州凭证测试有限公司",
        unified_social_credit_code="91320500VOUCHER0001",
        taxpayer_type="SMALL",
        industry="服务业",
    )
    db_session.add(enterprise)
    db_session.commit()
    return enterprise


def test_ensure_enterprise_subjects_creates_small_business_template(db_session):
    enterprise = make_enterprise(db_session)

    subjects = ensure_enterprise_subjects(db_session, enterprise_id=enterprise.id)

    codes = {subject.code for subject in subjects}
    assert "1002" in codes
    assert "1122" in codes
    assert "2202" in codes
    assert "22210101" in codes
    assert "22210102" in codes
    assert "5001" in codes
    assert "560201" in codes
    assert all(subject.organization_id == ORG for subject in subjects)
    assert all(subject.enterprise_id == enterprise.id for subject in subjects)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd finwise-accounting/backend
pytest tests/test_voucher_service.py::test_ensure_enterprise_subjects_creates_small_business_template -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.voucher_service'` or missing `AccountSubject`.

- [ ] **Step 3: Add the account subject ORM model**

In `finwise-accounting/backend/app/models/entities.py`, add `Boolean` to the SQLAlchemy imports and create `AccountSubject` after `MonthlyWorkPackage`:

```python
class AccountSubject(Base):
    __tablename__ = "account_subjects"
    __table_args__ = (
        UniqueConstraint("organization_id", "enterprise_id", "code", name="uq_account_subjects_enterprise_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    enterprise_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("enterprises.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(32))
    normal_balance: Mapped[str] = mapped_column(String(12))
    parent_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_leaf: Mapped[bool] = mapped_column(Boolean, default=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_voucher: Mapped[bool] = mapped_column(Boolean, default=True)
    is_common: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

- [ ] **Step 4: Export the model**

In `finwise-accounting/backend/app/models/__init__.py`, add `AccountSubject` to the import/export list.

- [ ] **Step 5: Create the small-business subject template**

Create `finwise-accounting/backend/app/accounting/subjects.py`:

```python
from __future__ import annotations

SMALL_BUSINESS_SUBJECTS: list[dict] = [
    {"code": "1001", "name": "库存现金", "category": "ASSET", "normal_balance": "DEBIT", "parent_code": None, "is_leaf": True, "allow_voucher": True, "is_common": False},
    {"code": "1002", "name": "银行存款", "category": "ASSET", "normal_balance": "DEBIT", "parent_code": None, "is_leaf": True, "allow_voucher": True, "is_common": True},
    {"code": "1122", "name": "应收账款", "category": "ASSET", "normal_balance": "DEBIT", "parent_code": None, "is_leaf": True, "allow_voucher": True, "is_common": True},
    {"code": "2202", "name": "应付账款", "category": "LIABILITY", "normal_balance": "CREDIT", "parent_code": None, "is_leaf": True, "allow_voucher": True, "is_common": True},
    {"code": "2221", "name": "应交税费", "category": "LIABILITY", "normal_balance": "CREDIT", "parent_code": None, "is_leaf": False, "allow_voucher": False, "is_common": True},
    {"code": "222101", "name": "应交增值税", "category": "LIABILITY", "normal_balance": "CREDIT", "parent_code": "2221", "is_leaf": False, "allow_voucher": False, "is_common": True},
    {"code": "22210101", "name": "进项税额", "category": "LIABILITY", "normal_balance": "DEBIT", "parent_code": "222101", "is_leaf": True, "allow_voucher": True, "is_common": True},
    {"code": "22210102", "name": "销项税额", "category": "LIABILITY", "normal_balance": "CREDIT", "parent_code": "222101", "is_leaf": True, "allow_voucher": True, "is_common": True},
    {"code": "5001", "name": "主营业务收入", "category": "PROFIT_LOSS", "normal_balance": "CREDIT", "parent_code": None, "is_leaf": True, "allow_voucher": True, "is_common": True},
    {"code": "5401", "name": "主营业务成本", "category": "PROFIT_LOSS", "normal_balance": "DEBIT", "parent_code": None, "is_leaf": True, "allow_voucher": True, "is_common": True},
    {"code": "5602", "name": "管理费用", "category": "PROFIT_LOSS", "normal_balance": "DEBIT", "parent_code": None, "is_leaf": False, "allow_voucher": False, "is_common": True},
    {"code": "560201", "name": "办公费", "category": "PROFIT_LOSS", "normal_balance": "DEBIT", "parent_code": "5602", "is_leaf": True, "allow_voucher": True, "is_common": True},
    {"code": "560202", "name": "差旅费", "category": "PROFIT_LOSS", "normal_balance": "DEBIT", "parent_code": "5602", "is_leaf": True, "allow_voucher": True, "is_common": True},
    {"code": "560203", "name": "服务费", "category": "PROFIT_LOSS", "normal_balance": "DEBIT", "parent_code": "5602", "is_leaf": True, "allow_voucher": True, "is_common": True},
    {"code": "5603", "name": "财务费用", "category": "PROFIT_LOSS", "normal_balance": "DEBIT", "parent_code": None, "is_leaf": False, "allow_voucher": False, "is_common": True},
    {"code": "560301", "name": "手续费", "category": "PROFIT_LOSS", "normal_balance": "DEBIT", "parent_code": "5603", "is_leaf": True, "allow_voucher": True, "is_common": True},
]
```

- [ ] **Step 6: Implement subject initialization**

Create `finwise-accounting/backend/app/services/voucher_service.py` with:

```python
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounting.subjects import SMALL_BUSINESS_SUBJECTS
from app.core.org_context import get_current_organization_id
from app.models import AccountSubject, Enterprise


class VoucherDomainError(Exception):
    pass


class VoucherValidationError(VoucherDomainError):
    pass


def ensure_enterprise_subjects(db: Session, *, enterprise_id: UUID) -> list[AccountSubject]:
    organization_id = get_current_organization_id()
    enterprise = db.get(Enterprise, enterprise_id)
    if enterprise is None or enterprise.organization_id != organization_id:
        raise VoucherDomainError("Enterprise not found.")

    existing = {
        subject.code: subject
        for subject in db.scalars(
            select(AccountSubject).where(
                AccountSubject.organization_id == organization_id,
                AccountSubject.enterprise_id == enterprise_id,
            )
        )
    }
    for item in SMALL_BUSINESS_SUBJECTS:
        if item["code"] in existing:
            continue
        db.add(AccountSubject(organization_id=organization_id, enterprise_id=enterprise_id, **item))
    db.commit()
    return list(
        db.scalars(
            select(AccountSubject)
            .where(AccountSubject.organization_id == organization_id, AccountSubject.enterprise_id == enterprise_id)
            .order_by(AccountSubject.code)
        )
    )
```

- [ ] **Step 7: Run the test**

Run:

```bash
cd finwise-accounting/backend
pytest tests/test_voucher_service.py::test_ensure_enterprise_subjects_creates_small_business_template -v
```

Expected: PASS.

---

## Task 2: Voucher Draft Models And Generation Service

**Files:**
- Modify: `finwise-accounting/backend/app/models/entities.py`
- Modify: `finwise-accounting/backend/app/models/__init__.py`
- Modify: `finwise-accounting/backend/app/services/voucher_service.py`
- Test: `finwise-accounting/backend/tests/test_voucher_service.py`

- [ ] **Step 1: Write the failing generation tests**

Append to `finwise-accounting/backend/tests/test_voucher_service.py`:

```python
from datetime import date
from decimal import Decimal

from app.models import BankTransaction, Invoice, MatchRecord, MonthlyWorkPackage
from app.services.voucher_service import generate_voucher_drafts


def make_package(db_session, enterprise):
    package = MonthlyWorkPackage(
        organization_id=ORG,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
    )
    db_session.add(package)
    db_session.commit()
    return package


def test_generate_voucher_drafts_for_matched_output_invoice_receipt(db_session):
    enterprise = make_enterprise(db_session)
    package = make_package(db_session, enterprise)
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 10),
        summary="收到客户货款",
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("1130.00"),
        counterparty_name="苏州客户有限公司",
    )
    invoice = Invoice(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        invoice_direction="OUTPUT",
        invoice_number="OUT-001",
        invoice_date=date(2026, 5, 9),
        amount=Decimal("1000.00"),
        tax_amount=Decimal("130.00"),
        total_amount=Decimal("1130.00"),
        seller_name=enterprise.name,
        buyer_name="苏州客户有限公司",
    )
    db_session.add_all([transaction, invoice])
    db_session.flush()
    db_session.add(
        MatchRecord(
            organization_id=ORG,
            monthly_work_package_id=package.id,
            bank_transaction_id=transaction.id,
            invoice_id=invoice.id,
            match_method="AUTO_EXACT",
            confidence=95,
            explanation="金额一致",
            confirmation_status="AUTO_CONFIRMED",
        )
    )
    db_session.commit()

    result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)

    assert result["created_vouchers"] == 1
    voucher = result["vouchers"][0]
    assert voucher.summary == "确认销售收入并收款"
    assert voucher.status == "PENDING_CONFIRMATION"
    assert voucher.ai_confidence == 92
    entries = sorted(voucher.entries, key=lambda item: (item.direction, item.account_code, item.amount))
    assert [(entry.direction, entry.account_code, str(entry.amount)) for entry in entries] == [
        ("CREDIT", "22210102", "130.00"),
        ("CREDIT", "5001", "1000.00"),
        ("DEBIT", "1002", "1130.00"),
    ]


def test_generate_voucher_drafts_for_unmatched_bank_fee(db_session):
    enterprise = make_enterprise(db_session)
    package = make_package(db_session, enterprise)
    transaction = BankTransaction(
        organization_id=ORG,
        monthly_work_package_id=package.id,
        transaction_date=date(2026, 5, 12),
        summary="银行手续费",
        debit_amount=Decimal("12.00"),
        credit_amount=Decimal("0.00"),
        counterparty_name="招商银行",
    )
    db_session.add(transaction)
    db_session.commit()

    result = generate_voucher_drafts(db_session, monthly_work_package_id=package.id)

    assert result["created_vouchers"] == 1
    voucher = result["vouchers"][0]
    assert voucher.summary == "支付银行手续费"
    assert voucher.ai_confidence == 88
    assert {(entry.direction, entry.account_code, str(entry.amount)) for entry in voucher.entries} == {
        ("DEBIT", "560301", "12.00"),
        ("CREDIT", "1002", "12.00"),
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd finwise-accounting/backend
pytest tests/test_voucher_service.py::test_generate_voucher_drafts_for_matched_output_invoice_receipt tests/test_voucher_service.py::test_generate_voucher_drafts_for_unmatched_bank_fee -v
```

Expected: FAIL with missing `generate_voucher_drafts` or missing voucher models.

- [ ] **Step 3: Add voucher ORM models**

In `finwise-accounting/backend/app/models/entities.py`, add these after `VoucherRule` or after `AccountSubject`:

```python
class VoucherRule(Base):
    __tablename__ = "voucher_rules"
    __table_args__ = (
        UniqueConstraint("organization_id", "enterprise_id", "rule_name", name="uq_voucher_rules_enterprise_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    enterprise_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("enterprises.id"), index=True)
    rule_name: Mapped[str] = mapped_column(String(120))
    summary_keywords: Mapped[list] = mapped_column(JSON, default=list)
    counterparty_pattern: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    source_direction: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    invoice_direction: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    summary_template: Mapped[str] = mapped_column(String(160))
    debit_account_code: Mapped[str] = mapped_column(String(32))
    credit_account_code: Mapped[str] = mapped_column(String(32))
    tax_account_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    require_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Voucher(Base):
    __tablename__ = "vouchers"
    __table_args__ = (
        UniqueConstraint("monthly_work_package_id", "source_key", name="uq_vouchers_package_source_key"),
        CheckConstraint("ai_confidence >= 0 AND ai_confidence <= 100", name="ck_vouchers_ai_confidence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("monthly_work_packages.id"), index=True)
    voucher_date: Mapped[date] = mapped_column(Date)
    voucher_number: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    summary: Mapped[str] = mapped_column(String(180))
    attachment_count: Mapped[int] = mapped_column(Integer, default=0)
    source_key: Mapped[str] = mapped_column(String(160))
    source_data: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_confidence: Mapped[int] = mapped_column(Integer, default=0)
    ai_reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="PENDING_CONFIRMATION")
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VoucherEntry(Base):
    __tablename__ = "voucher_entries"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4, primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=DEFAULT_CHANNEL_ID, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id"), index=True)
    voucher_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("vouchers.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(String(8))
    account_code: Mapped[str] = mapped_column(String(32))
    account_name: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))
```

Add a relationship on `Voucher`:

```python
entries: Mapped[list["VoucherEntry"]] = relationship("VoucherEntry", cascade="all, delete-orphan", order_by="VoucherEntry.line_no")
```

Add `relationship` to imports from `sqlalchemy.orm`.

- [ ] **Step 4: Export models**

Add `VoucherRule`, `Voucher`, and `VoucherEntry` to `finwise-accounting/backend/app/models/__init__.py`.

- [ ] **Step 5: Implement voucher draft generation**

Extend `finwise-accounting/backend/app/services/voucher_service.py` with helpers that:

```python
def generate_voucher_drafts(db: Session, *, monthly_work_package_id: UUID) -> dict:
    package = _get_package(db, monthly_work_package_id)
    enterprise = db.get(Enterprise, package.enterprise_id)
    if enterprise is None:
        raise VoucherDomainError("Enterprise not found.")
    ensure_enterprise_subjects(db, enterprise_id=enterprise.id)
    existing_keys = set(
        db.scalars(select(Voucher.source_key).where(Voucher.monthly_work_package_id == package.id))
    )
    created = []
    for match in _confirmed_matches(db, package.id):
        source_key = f"match:{match.id}"
        if source_key in existing_keys:
            continue
        voucher = _voucher_from_match(db, package=package, match=match, source_key=source_key)
        if voucher is not None:
            db.add(voucher)
            created.append(voucher)
            existing_keys.add(source_key)
    for transaction in _unvouchered_bank_transactions(db, package.id, existing_keys):
        source_key = f"bank:{transaction.id}"
        voucher = _voucher_from_bank_transaction(package=package, transaction=transaction, source_key=source_key)
        if voucher is not None:
            db.add(voucher)
            created.append(voucher)
            existing_keys.add(source_key)
    db.flush()
    for voucher in created:
        voucher.validation_errors = validate_voucher(db, voucher=voucher)
    db.commit()
    for voucher in created:
        db.refresh(voucher)
    return {"created_vouchers": len(created), "vouchers": created}
```

Use these exact scenario rules:

```python
# OUTPUT invoice with matched receipt:
# DEBIT 1002 total_amount
# CREDIT 5001 amount
# CREDIT 22210102 tax_amount
# summary: 确认销售收入并收款
# confidence: 92

# INPUT invoice with matched payment:
# DEBIT 560203 amount
# DEBIT 22210101 tax_amount
# CREDIT 1002 total_amount
# summary: 确认费用并付款
# confidence: 82

# bank summary containing 手续费:
# DEBIT 560301 transaction amount
# CREDIT 1002 transaction amount
# summary: 支付银行手续费
# confidence: 88
```

Implement `validate_voucher(db, voucher)` to return these string codes:

```python
["DEBIT_CREDIT_NOT_EQUAL", "SUBJECT_NOT_ENABLED", "SUBJECT_NOT_LEAF", "ZERO_AMOUNT", "DATE_OUT_OF_PERIOD"]
```

- [ ] **Step 6: Run generation tests**

Run:

```bash
cd finwise-accounting/backend
pytest tests/test_voucher_service.py -v
```

Expected: PASS.

---

## Task 3: Voucher Confirmation And API

**Files:**
- Create: `finwise-accounting/backend/app/schemas/voucher.py`
- Create: `finwise-accounting/backend/app/api/vouchers.py`
- Modify: `finwise-accounting/backend/app/main.py`
- Modify: `finwise-accounting/backend/app/services/voucher_service.py`
- Test: `finwise-accounting/backend/tests/test_voucher_api.py`

- [ ] **Step 1: Write API lifecycle tests**

Create `finwise-accounting/backend/tests/test_voucher_api.py` with a TestClient setup copied from `test_matching_workflow_api.py`, then add:

```python
def test_subjects_endpoint_initializes_and_lists_subjects():
    client, db_session = make_context()
    enterprise, _package = make_package(db_session)

    response = client.post(f"/api/enterprises/{enterprise.id}/account-subjects/initialize")

    assert response.status_code == 201
    payload = response.json()
    assert any(subject["code"] == "1002" for subject in payload)
    assert any(subject["code"] == "560201" for subject in payload)

    list_response = client.get(f"/api/enterprises/{enterprise.id}/account-subjects")
    assert list_response.status_code == 200
    assert len(list_response.json()) >= 10


def test_generate_and_confirm_voucher_api():
    client, db_session = make_context()
    enterprise, package = make_package(db_session)
    add_output_match(db_session, enterprise, package)

    generate_response = client.post(f"/api/monthly-packages/{package.id}/vouchers/generate")

    assert generate_response.status_code == 201
    payload = generate_response.json()
    assert payload["created_vouchers"] == 1
    voucher_id = payload["vouchers"][0]["id"]
    assert payload["vouchers"][0]["status"] == "PENDING_CONFIRMATION"

    confirm_response = client.post(f"/api/vouchers/{voucher_id}/confirm", json={"confirmed_by": "operator"})

    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["voucher_number"] == "记-0001"
```

Define `add_output_match` in the test file using the same data from Task 2.

- [ ] **Step 2: Run API tests to verify they fail**

Run:

```bash
cd finwise-accounting/backend
pytest tests/test_voucher_api.py -v
```

Expected: FAIL with 404 for voucher routes.

- [ ] **Step 3: Add voucher schemas**

Create `finwise-accounting/backend/app/schemas/voucher.py`:

```python
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AccountSubjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    enterprise_id: UUID
    code: str
    name: str
    category: str
    normal_balance: str
    parent_code: str | None
    is_leaf: bool
    is_enabled: bool
    allow_voucher: bool
    is_common: bool


class VoucherEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_no: int
    direction: str
    account_code: str
    account_name: str
    amount: Decimal
    source_type: str
    source_id: str


class VoucherRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    monthly_work_package_id: UUID
    voucher_date: date
    voucher_number: str | None
    summary: str
    attachment_count: int
    source_key: str
    source_data: dict
    ai_confidence: int
    ai_reason: str
    status: str
    validation_errors: list[str]
    confirmed_by: str | None
    confirmed_at: datetime | None
    entries: list[VoucherEntryRead]


class VoucherGenerateResponse(BaseModel):
    created_vouchers: int
    vouchers: list[VoucherRead]


class VoucherConfirmRequest(BaseModel):
    confirmed_by: str = "operator"
```

- [ ] **Step 4: Add API router**

Create `finwise-accounting/backend/app/api/vouchers.py`:

```python
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.voucher import AccountSubjectRead, VoucherConfirmRequest, VoucherGenerateResponse, VoucherRead
from app.services.voucher_service import (
    VoucherDomainError,
    VoucherValidationError,
    confirm_voucher,
    ensure_enterprise_subjects,
    generate_voucher_drafts,
    list_enterprise_subjects,
    list_package_vouchers,
)

router = APIRouter(tags=["vouchers"])


@router.post("/api/enterprises/{enterprise_id}/account-subjects/initialize", response_model=list[AccountSubjectRead], status_code=status.HTTP_201_CREATED)
def initialize_subjects_endpoint(enterprise_id: UUID, db: Session = Depends(get_db)):
    try:
        return ensure_enterprise_subjects(db, enterprise_id=enterprise_id)
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/enterprises/{enterprise_id}/account-subjects", response_model=list[AccountSubjectRead])
def list_subjects_endpoint(enterprise_id: UUID, db: Session = Depends(get_db)):
    return list_enterprise_subjects(db, enterprise_id=enterprise_id)


@router.post("/api/monthly-packages/{package_id}/vouchers/generate", response_model=VoucherGenerateResponse, status_code=status.HTTP_201_CREATED)
def generate_vouchers_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    try:
        return generate_voucher_drafts(db, monthly_work_package_id=package_id)
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/api/monthly-packages/{package_id}/vouchers", response_model=list[VoucherRead])
def list_vouchers_endpoint(package_id: UUID, db: Session = Depends(get_db)):
    return list_package_vouchers(db, monthly_work_package_id=package_id)


@router.post("/api/vouchers/{voucher_id}/confirm", response_model=VoucherRead)
def confirm_voucher_endpoint(voucher_id: UUID, payload: VoucherConfirmRequest, db: Session = Depends(get_db)):
    try:
        return confirm_voucher(db, voucher_id=voucher_id, confirmed_by=payload.confirmed_by)
    except VoucherValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except VoucherDomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

- [ ] **Step 5: Implement API service functions**

Add to `voucher_service.py`:

```python
def list_enterprise_subjects(db: Session, *, enterprise_id: UUID) -> list[AccountSubject]:
    ensure_enterprise_subjects(db, enterprise_id=enterprise_id)
    return list(db.scalars(select(AccountSubject).where(AccountSubject.enterprise_id == enterprise_id).order_by(AccountSubject.code)))


def list_package_vouchers(db: Session, *, monthly_work_package_id: UUID) -> list[Voucher]:
    package = _get_package(db, monthly_work_package_id)
    return list(db.scalars(select(Voucher).where(Voucher.monthly_work_package_id == package.id).order_by(Voucher.voucher_date, Voucher.created_at, Voucher.id)))


def confirm_voucher(db: Session, *, voucher_id: UUID, confirmed_by: str = "operator") -> Voucher:
    voucher = db.get(Voucher, voucher_id)
    if voucher is None:
        raise VoucherDomainError("Voucher not found.")
    voucher.validation_errors = validate_voucher(db, voucher=voucher)
    if voucher.validation_errors:
        raise VoucherValidationError("Voucher has validation errors.")
    voucher.status = "CONFIRMED"
    voucher.confirmed_by = confirmed_by
    voucher.confirmed_at = datetime.utcnow()
    if not voucher.voucher_number:
        voucher.voucher_number = _next_voucher_number(db, voucher.monthly_work_package_id)
    db.add(AuditLog(organization_id=voucher.organization_id, monthly_work_package_id=voucher.monthly_work_package_id, action="CONFIRM_VOUCHER", before_data={}, after_data={"voucher_id": str(voucher.id), "voucher_number": voucher.voucher_number}))
    db.commit()
    db.refresh(voucher)
    return voucher
```

`_next_voucher_number` counts confirmed vouchers in the same package and returns `记-0001`, `记-0002`, etc.

- [ ] **Step 6: Wire router into app**

In `finwise-accounting/backend/app/main.py`, import and include:

```python
from app.api.vouchers import router as vouchers_router
...
app.include_router(vouchers_router)
```

- [ ] **Step 7: Run API tests**

Run:

```bash
cd finwise-accounting/backend
pytest tests/test_voucher_api.py tests/test_voucher_service.py -v
```

Expected: PASS.

---

## Task 4: Frontend API, Routes, And Subject Settings Page

**Files:**
- Modify: `finwise-accounting/frontend/src/api/client.js`
- Modify: `finwise-accounting/frontend/src/router/index.js`
- Create: `finwise-accounting/frontend/src/views/AccountSubjectsView.vue`
- Create: `finwise-accounting/frontend/src/views/AccountSubjectsView.spec.js`

- [ ] **Step 1: Write source-level UI test**

Create `finwise-accounting/frontend/src/views/AccountSubjectsView.spec.js`:

```javascript
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'AccountSubjectsView.vue'), 'utf8')
const apiSource = readFileSync(resolve(__dirname, '../api/client.js'), 'utf8')
const routerSource = readFileSync(resolve(__dirname, '../router/index.js'), 'utf8')

describe('AccountSubjectsView', () => {
  it('loads and initializes enterprise accounting subjects', () => {
    expect(source).toContain('科目设置')
    expect(source).toContain('初始化科目')
    expect(source).toContain('api.accountSubjects.initialize')
    expect(source).toContain('api.accountSubjects.list')
    expect(source).toContain('allow_voucher')
    expect(apiSource).toContain('accountSubjects')
    expect(routerSource).toContain('/account-subjects')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd finwise-accounting/frontend
npm test -- AccountSubjectsView.spec.js
```

Expected: FAIL with missing file or route/API strings.

- [ ] **Step 3: Add API client methods**

In `frontend/src/api/client.js`, add:

```javascript
accountSubjects: {
  list: (enterpriseId) => apiClient.get(`/enterprises/${enterpriseId}/account-subjects`),
  initialize: (enterpriseId) => apiClient.post(`/enterprises/${enterpriseId}/account-subjects/initialize`),
},
```

- [ ] **Step 4: Add route**

In `frontend/src/router/index.js`, add:

```javascript
{
  path: '/account-subjects',
  name: 'account-subjects',
  component: () => import('../views/AccountSubjectsView.vue'),
},
```

- [ ] **Step 5: Create subject settings page**

Create `frontend/src/views/AccountSubjectsView.vue` with:

```vue
<template>
  <section class="subjects-layout">
    <div class="panel">
      <div class="panel-header">
        <div>
          <h2 class="section-title">科目设置</h2>
          <p class="caption">每个企业使用小企业会计准则科目表，可启用常用末级科目生成凭证。</p>
        </div>
        <div class="toolbar">
          <el-select v-model="selectedEnterpriseId" placeholder="选择企业" filterable style="width: 260px" @change="loadSubjects">
            <el-option v-for="enterprise in workspace.enterprises" :key="enterprise.id" :label="enterprise.name" :value="enterprise.id" />
          </el-select>
          <el-button type="primary" :loading="isInitializing" @click="initializeSubjects">初始化科目</el-button>
        </div>
      </div>
      <el-table v-loading="isLoading" :data="subjects" stripe>
        <el-table-column prop="code" label="科目编码" width="120" />
        <el-table-column prop="name" label="科目名称" min-width="160" />
        <el-table-column prop="category" label="类别" width="130" />
        <el-table-column prop="normal_balance" label="方向" width="100" />
        <el-table-column label="末级" width="80">
          <template #default="{ row }">{{ row.is_leaf ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column label="可用于凭证" width="120">
          <template #default="{ row }">{{ row.allow_voucher ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">{{ row.is_enabled ? '启用' : '停用' }}</template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { onMounted, ref, watch } from 'vue'
import { api } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const selectedEnterpriseId = ref('')
const subjects = ref([])
const isLoading = ref(false)
const isInitializing = ref(false)

watch(
  () => workspace.enterprises,
  (enterprises) => {
    if (!selectedEnterpriseId.value && enterprises.length) {
      selectedEnterpriseId.value = enterprises[0].id
      loadSubjects()
    }
  },
  { immediate: true },
)

onMounted(() => {
  if (selectedEnterpriseId.value) loadSubjects()
})

async function loadSubjects() {
  if (!selectedEnterpriseId.value) return
  isLoading.value = true
  try {
    const response = await api.accountSubjects.list(selectedEnterpriseId.value)
    subjects.value = response.data
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '科目加载失败')
  } finally {
    isLoading.value = false
  }
}

async function initializeSubjects() {
  if (!selectedEnterpriseId.value) {
    ElMessage.warning('请先选择企业')
    return
  }
  isInitializing.value = true
  try {
    const response = await api.accountSubjects.initialize(selectedEnterpriseId.value)
    subjects.value = response.data
    ElMessage.success('科目已初始化')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '科目初始化失败')
  } finally {
    isInitializing.value = false
  }
}
</script>

<style scoped>
.subjects-layout { display: grid; gap: 16px; }
.panel { padding: 16px; border: 1px solid var(--fw-line); border-radius: var(--fw-radius); background: var(--fw-surface); }
.panel-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.toolbar { display: flex; gap: 8px; align-items: center; }
@media (max-width: 900px) { .panel-header, .toolbar { display: grid; } }
</style>
```

- [ ] **Step 6: Run frontend test**

Run:

```bash
cd finwise-accounting/frontend
npm test -- AccountSubjectsView.spec.js
```

Expected: PASS.

---

## Task 5: Voucher Workbench Frontend

**Files:**
- Modify: `finwise-accounting/frontend/src/api/client.js`
- Modify: `finwise-accounting/frontend/src/router/index.js`
- Create: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.vue`
- Create: `finwise-accounting/frontend/src/views/VoucherWorkbenchView.spec.js`

- [ ] **Step 1: Write source-level UI test**

Create `frontend/src/views/VoucherWorkbenchView.spec.js`:

```javascript
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'VoucherWorkbenchView.vue'), 'utf8')
const apiSource = readFileSync(resolve(__dirname, '../api/client.js'), 'utf8')
const routerSource = readFileSync(resolve(__dirname, '../router/index.js'), 'utf8')

describe('VoucherWorkbenchView', () => {
  it('supports voucher generation, filtering, detail review, and confirmation', () => {
    expect(source).toContain('凭证生成工作台')
    expect(source).toContain('生成凭证草稿')
    expect(source).toContain('AI 置信度')
    expect(source).toContain('借方')
    expect(source).toContain('贷方')
    expect(source).toContain('api.vouchers.generate')
    expect(source).toContain('api.vouchers.confirm')
    expect(apiSource).toContain('vouchers')
    expect(routerSource).toContain('/vouchers')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd finwise-accounting/frontend
npm test -- VoucherWorkbenchView.spec.js
```

Expected: FAIL.

- [ ] **Step 3: Add voucher API client**

In `frontend/src/api/client.js`, add:

```javascript
vouchers: {
  list: (packageId) => apiClient.get(`/monthly-packages/${packageId}/vouchers`),
  generate: (packageId) => apiClient.post(`/monthly-packages/${packageId}/vouchers/generate`),
  confirm: (voucherId, payload) => apiClient.post(`/vouchers/${voucherId}/confirm`, payload),
},
```

- [ ] **Step 4: Add route**

In `frontend/src/router/index.js`, add:

```javascript
{
  path: '/vouchers',
  name: 'vouchers',
  component: () => import('../views/VoucherWorkbenchView.vue'),
},
```

- [ ] **Step 5: Create voucher workbench**

Create `frontend/src/views/VoucherWorkbenchView.vue` with a two-column layout:

```vue
<template>
  <section class="voucher-workbench">
    <div class="panel">
      <div class="panel-header">
        <div>
          <h2 class="section-title">凭证生成工作台</h2>
          <p class="caption">根据流水、发票和匹配结果生成凭证草稿，确认后形成正式凭证。</p>
        </div>
        <div class="toolbar">
          <el-button :loading="isLoading" @click="loadVouchers">刷新</el-button>
          <el-button type="primary" :loading="isGenerating" @click="generateVouchers">生成凭证草稿</el-button>
        </div>
      </div>
      <el-segmented v-model="activeFilter" :options="filterOptions" />
      <el-table v-loading="isLoading" :data="filteredVouchers" class="voucher-table" stripe @row-click="selectVoucher">
        <el-table-column prop="voucher_date" label="日期" width="110" />
        <el-table-column prop="voucher_number" label="凭证号" width="110" />
        <el-table-column prop="summary" label="摘要" min-width="180" show-overflow-tooltip />
        <el-table-column prop="ai_confidence" label="AI 置信度" width="110" align="right" />
        <el-table-column label="状态" width="130">
          <template #default="{ row }">{{ statusLabel(row.status) }}</template>
        </el-table-column>
      </el-table>
    </div>

    <div class="panel detail-panel">
      <template v-if="selectedVoucher">
        <div class="detail-title">
          <h3>{{ selectedVoucher.summary }}</h3>
          <span>AI 置信度：{{ selectedVoucher.ai_confidence }}</span>
        </div>
        <p class="caption">{{ selectedVoucher.ai_reason }}</p>
        <el-table :data="selectedVoucher.entries" size="small">
          <el-table-column label="方向" width="80">
            <template #default="{ row }">{{ row.direction === 'DEBIT' ? '借方' : '贷方' }}</template>
          </el-table-column>
          <el-table-column label="科目" min-width="180">
            <template #default="{ row }">{{ row.account_code }} {{ row.account_name }}</template>
          </el-table-column>
          <el-table-column prop="amount" label="金额" width="120" align="right" />
        </el-table>
        <div v-if="selectedVoucher.validation_errors?.length" class="errors">
          <strong>校验异常</strong>
          <span v-for="error in selectedVoucher.validation_errors" :key="error">{{ error }}</span>
        </div>
        <el-button type="primary" :disabled="selectedVoucher.status === 'CONFIRMED' || selectedVoucher.validation_errors?.length" :loading="isConfirming" @click="confirmSelected">
          确认凭证
        </el-button>
      </template>
      <el-empty v-else description="请选择左侧凭证查看详情" />
    </div>
  </section>
</template>
```

Use `script setup` to load `workspace.activePackage`, call `api.vouchers.list`, `api.vouchers.generate`, and `api.vouchers.confirm({ confirmed_by: 'operator' })`. Add filters: 全部, 待确认, 已确认, 异常.

- [ ] **Step 6: Run frontend test**

Run:

```bash
cd finwise-accounting/frontend
npm test -- VoucherWorkbenchView.spec.js
```

Expected: PASS.

---

## Task 6: Navigation And Workspace Integration

**Files:**
- Modify: likely `finwise-accounting/frontend/src/App.vue` or `finwise-accounting/frontend/src/views/WorkspaceHomeView.vue`
- Test: existing frontend source tests or new source assertion if navigation lives in a view

- [ ] **Step 1: Locate navigation**

Run:

```bash
cd finwise-accounting/frontend
rg "账目明细|规则设置|输出中心|router-link|el-menu" src
```

Expected: identify the file that renders main navigation.

- [ ] **Step 2: Add navigation items**

Add links for:

```text
科目设置 -> /account-subjects
凭证管理 -> /vouchers
```

Use the same style as existing navigation.

- [ ] **Step 3: Add or update source test**

If navigation is in `WorkspaceHomeView.vue`, add assertions to its existing spec:

```javascript
expect(source).toContain('科目设置')
expect(source).toContain('/account-subjects')
expect(source).toContain('凭证管理')
expect(source).toContain('/vouchers')
```

- [ ] **Step 4: Run frontend tests**

Run:

```bash
cd finwise-accounting/frontend
npm test -- --run
```

Expected: PASS.

---

## Task 7: Final Backend/Frontend Verification

**Files:**
- No code changes unless verification finds defects.

- [ ] **Step 1: Run backend voucher tests**

Run:

```bash
cd finwise-accounting/backend
pytest tests/test_voucher_service.py tests/test_voucher_api.py -v
```

Expected: PASS.

- [ ] **Step 2: Run broader backend regression slice**

Run:

```bash
cd finwise-accounting/backend
pytest tests/test_matching_workflow_api.py tests/test_end_to_end_monthly_flow.py tests/test_statement_and_tax.py -v
```

Expected: PASS.

- [ ] **Step 3: Run frontend tests**

Run:

```bash
cd finwise-accounting/frontend
npm test -- --run
```

Expected: PASS.

- [ ] **Step 4: Start local app for manual smoke**

Run backend and frontend according to existing project commands:

```bash
cd finwise-accounting/backend
uvicorn app.main:app --reload --port 8000
```

```bash
cd finwise-accounting/frontend
npm run dev -- --host 127.0.0.1
```

Open the frontend, then verify:

```text
1. 科目设置 page loads.
2. 初始化科目 returns the small-business subject list.
3. 凭证管理 page loads.
4. 生成凭证草稿 creates voucher rows after existing import/matching sample data.
5. Selecting a voucher shows debit and credit entries.
6. Valid voucher confirms and receives voucher number 记-0001.
```

---

## Self-Review

- Spec coverage: The delivered first implementation covers subject initialization/listing, voucher draft generation/listing/confirmation, validation, outputs, and frontend navigation/workbench pages. Rule memory, rule creation schemas, subject edit controls, and reject controls are model-reserved or deferred follow-ups alongside full posting, close/reopen periods, print templates, payroll accruals, depreciation, auxiliary accounting, multi-ledger, and multi-currency.
- Placeholder scan: No `TBD`, `TODO`, or vague "add tests" steps remain; each task has concrete files, commands, and expected outcomes.
- Type consistency: Backend names use `AccountSubject`, `VoucherRule`, `Voucher`, `VoucherEntry`, `generate_voucher_drafts`, `confirm_voucher`; frontend API names use `accountSubjects` and `vouchers` consistently.
