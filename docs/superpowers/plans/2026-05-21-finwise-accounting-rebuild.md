# FinWise Accounting Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new isolated `finwise-accounting/` application for Suzhou bookkeeping agencies to manage enterprise initialization, monthly work packages, imports, reconciliation, filing assistance, and boss-facing reports.

**Architecture:** Create a fresh Vue 3 + Element Plus frontend and FastAPI backend under `finwise-accounting/`. The backend owns domain models, imports, matching, statements, filing, reports, and audit records; the frontend is organized around enterprise initialization and monthly work packages. The old root `backend/` and `frontend/` directories are read-only references and must not be modified.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, PostgreSQL-compatible SQLite test mode, pytest, openpyxl, pandas, Vue 3, Vite, Pinia, Element Plus, ECharts, Vitest, Playwright.

---

## Reference Inputs

- Product spec: `docs/superpowers/specs/2026-05-21-finwise-accounting-rebuild-design.md`
- UI reference: `/Volumes/DiskA/lls/qiyoutong-ui-spec.html`
- UI constraints to apply:
  - Quiet enterprise backend, not marketing-style.
  - Left navigation plus dense work surface.
  - Table-first workflows, charts only for decisions.
  - Main color `#1769E0`, success `#16855C`, warning `#B56A12`, danger `#C24136`, ink `#172033`.
  - Background `#F6F8FB`, surface `#FFFFFF`, line `#D9E2EF`.
  - Card radius 8px, button/input radius 6px.
  - Font stack: `-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`.
  - Page title 24px/800, section title 18px/800, body 15px, captions 12px.
  - Status labels must be business states: 待导入, 待确认, 已确认, 待补资料, 可导出, 已导出, 数据不足.

## File Structure

Create this new tree. Do not modify root `backend/` or root `frontend/`.

```text
finwise-accounting/
├── README.md
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── deps.py
│   │   │   ├── enterprises.py
│   │   │   ├── imports.py
│   │   │   ├── matching.py
│   │   │   ├── reports.py
│   │   │   ├── statements.py
│   │   │   └── tax.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   └── org_context.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── entities.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── enterprise.py
│   │   │   ├── import_batch.py
│   │   │   ├── matching.py
│   │   │   ├── monthly.py
│   │   │   ├── report.py
│   │   │   ├── statement.py
│   │   │   └── tax.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── enterprise_service.py
│   │   │   ├── import_service.py
│   │   │   ├── matching_service.py
│   │   │   ├── report_service.py
│   │   │   ├── statement_service.py
│   │   │   └── tax_service.py
│   │   ├── rules/
│   │   │   ├── __init__.py
│   │   │   └── built_in.py
│   │   └── reports/
│   │       ├── __init__.py
│   │       ├── monthly_brief.py
│   │       └── health_diagnosis.py
│   └── tests/
│       ├── conftest.py
│       ├── test_enterprise_initialization.py
│       ├── test_import_service.py
│       ├── test_matching_service.py
│       ├── test_statement_and_tax.py
│       └── test_reports_and_privacy.py
└── frontend/
    ├── package.json
    ├── index.html
    ├── vite.config.js
    └── src/
        ├── main.js
        ├── App.vue
        ├── api/
        │   └── client.js
        ├── router/
        │   └── index.js
        ├── stores/
        │   └── workspace.js
        ├── styles/
        │   ├── tokens.css
        │   └── base.css
        ├── components/
        │   ├── AppLayout.vue
        │   ├── StatusTag.vue
        │   ├── MetricCard.vue
        │   └── DataTableShell.vue
        └── views/
            ├── EnterpriseListView.vue
            ├── EnterpriseInitView.vue
            ├── MonthlyWorkspaceView.vue
            ├── AccountDetailsView.vue
            └── OutputCenterView.vue
```

## Task 1: Scaffold Isolated Project

**Files:**
- Create: `finwise-accounting/README.md`
- Create: `finwise-accounting/backend/pyproject.toml`
- Create: `finwise-accounting/backend/app/main.py`
- Create: `finwise-accounting/backend/app/core/config.py`
- Create: `finwise-accounting/backend/app/core/database.py`
- Create: `finwise-accounting/backend/app/core/org_context.py`
- Create: empty `__init__.py` files in backend packages
- Create: `finwise-accounting/backend/tests/conftest.py`
- Create: `finwise-accounting/frontend/package.json`
- Create: `finwise-accounting/frontend/index.html`
- Create: `finwise-accounting/frontend/vite.config.js`
- Create: `finwise-accounting/frontend/src/main.js`
- Create: `finwise-accounting/frontend/src/App.vue`

- [ ] **Step 1: Create backend project metadata**

Create `finwise-accounting/backend/pyproject.toml`:

```toml
[project]
name = "finwise-accounting-backend"
version = "0.1.0"
description = "Monthly bookkeeping agency workflow backend for FinWise Accounting"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.111.0",
  "uvicorn[standard]>=0.30.0",
  "sqlalchemy>=2.0.30",
  "pydantic>=2.7.0",
  "pydantic-settings>=2.2.1",
  "python-multipart>=0.0.9",
  "pandas>=2.2.2",
  "openpyxl>=3.1.2",
  "jinja2>=3.1.4",
]

[project.optional-dependencies]
test = [
  "pytest>=8.2.0",
  "httpx>=0.27.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 2: Create backend settings**

Create `finwise-accounting/backend/app/core/config.py`:

```python
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "FinWise Accounting"
    database_url: str = "sqlite:///./finwise_accounting.db"
    upload_dir: Path = Path("storage/uploads")
    default_organization_id: str = "00000000-0000-0000-0000-000000000001"
    enable_ai: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 3: Create database session helpers**

Create `finwise-accounting/backend/app/core/database.py`:

```python
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _connect_args(url: str) -> dict[str, bool]:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


settings = get_settings()
engine = create_engine(settings.database_url, connect_args=_connect_args(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 4: Create organization context slot**

Create `finwise-accounting/backend/app/core/org_context.py`:

```python
from uuid import UUID

from app.core.config import get_settings


def get_current_organization_id() -> UUID:
    return UUID(get_settings().default_organization_id)
```

- [ ] **Step 5: Create FastAPI app**

Create `finwise-accounting/backend/app/main.py`:

```python
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="FinWise Accounting API")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 6: Create backend test fixture**

Create `finwise-accounting/backend/tests/conftest.py`:

```python
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 7: Create frontend package**

Create `finwise-accounting/frontend/package.json`:

```json
{
  "name": "finwise-accounting-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "@element-plus/icons-vue": "^2.3.1",
    "@vitejs/plugin-vue": "^5.0.5",
    "axios": "^1.7.2",
    "echarts": "^5.5.0",
    "element-plus": "^2.7.5",
    "pinia": "^2.1.7",
    "vite": "^5.2.12",
    "vue": "^3.4.27",
    "vue-router": "^4.3.2"
  },
  "devDependencies": {
    "vitest": "^1.6.0"
  }
}
```

- [ ] **Step 8: Create frontend entry files**

Create `finwise-accounting/frontend/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>智税管家 · 代账月度工作台</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
```

Create `finwise-accounting/frontend/vite.config.js`:

```javascript
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5174,
  },
})
```

Create `finwise-accounting/frontend/src/main.js`:

```javascript
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/tokens.css'
import './styles/base.css'
import App from './App.vue'

createApp(App).use(createPinia()).use(ElementPlus).mount('#app')
```

Create `finwise-accounting/frontend/src/App.vue`:

```vue
<template>
  <div class="app-root">
    智税管家 · 代账月度工作台
  </div>
</template>
```

- [ ] **Step 9: Run scaffold checks**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
python -m pytest -q
```

Expected: pytest starts and reports no tests collected or all scaffold tests passing.

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm install
npm run build
```

Expected: Vite build succeeds.

- [ ] **Step 10: Commit scaffold**

```bash
git add finwise-accounting
git commit -m "feat(accounting): scaffold isolated rebuild app"
```

## Task 2: Backend Domain Models And Schemas

**Files:**
- Create: `finwise-accounting/backend/app/models/entities.py`
- Create: `finwise-accounting/backend/app/schemas/enterprise.py`
- Create: `finwise-accounting/backend/app/schemas/import_batch.py`
- Create: `finwise-accounting/backend/app/schemas/matching.py`
- Create: `finwise-accounting/backend/app/schemas/monthly.py`
- Create: `finwise-accounting/backend/app/schemas/report.py`
- Create: `finwise-accounting/backend/app/schemas/statement.py`
- Create: `finwise-accounting/backend/app/schemas/tax.py`
- Modify: `finwise-accounting/backend/app/main.py`
- Test: `finwise-accounting/backend/tests/test_enterprise_initialization.py`

- [ ] **Step 1: Write failing model test**

Create `finwise-accounting/backend/tests/test_enterprise_initialization.py`:

```python
from uuid import UUID

from app.models.entities import Enterprise, InitialFinancialSnapshot, MonthlyWorkPackage


def test_enterprise_monthly_package_keeps_org_and_period(db_session):
    enterprise = Enterprise(
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        name="苏州样例科技有限公司",
        unified_social_credit_code="91320500TEST000001",
        taxpayer_type="GENERAL",
        industry="制造业",
        province="江苏省",
        city="苏州市",
    )
    db_session.add(enterprise)
    db_session.flush()

    snapshot = InitialFinancialSnapshot(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
        balance_sheet_data={"资产总计": 1000000, "负债合计": 400000, "所有者权益合计": 600000},
        income_statement_data={"营业收入": 800000, "净利润": 90000},
        validation_result={"balanced": True},
    )
    package = MonthlyWorkPackage(
        organization_id=enterprise.organization_id,
        enterprise_id=enterprise.id,
        period_year=2026,
        period_month=5,
    )
    db_session.add_all([snapshot, package])
    db_session.commit()

    assert package.enterprise_id == enterprise.id
    assert package.organization_id == UUID("00000000-0000-0000-0000-000000000001")
    assert package.period_year == 2026
    assert package.period_month == 5
    assert snapshot.validation_result["balanced"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
python -m pytest tests/test_enterprise_initialization.py -q
```

Expected: FAIL because `app.models.entities` does not exist.

- [ ] **Step 3: Implement SQLAlchemy models**

Create `finwise-accounting/backend/app/models/entities.py` with enums as strings and JSON fields:

```python
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def new_uuid() -> str:
    return str(uuid4())


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="默认代账机构")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Enterprise(Base):
    __tablename__ = "enterprises"
    __table_args__ = (UniqueConstraint("organization_id", "unified_social_credit_code"),)

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    unified_social_credit_code: Mapped[str] = mapped_column(String(32), index=True)
    taxpayer_type: Mapped[str] = mapped_column(String(20))
    industry: Mapped[str] = mapped_column(String(80))
    province: Mapped[str] = mapped_column(String(40), default="江苏省")
    city: Mapped[str] = mapped_column(String(40), default="苏州市")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InitialFinancialSnapshot(Base):
    __tablename__ = "initial_financial_snapshots"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    enterprise_id: Mapped[UUID] = mapped_column(ForeignKey("enterprises.id"), index=True)
    balance_sheet_data: Mapped[dict] = mapped_column(JSON, default=dict)
    income_statement_data: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MonthlyWorkPackage(Base):
    __tablename__ = "monthly_work_packages"
    __table_args__ = (UniqueConstraint("organization_id", "enterprise_id", "period_year", "period_month"),)

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    enterprise_id: Mapped[UUID] = mapped_column(ForeignKey("enterprises.id"), index=True)
    period_year: Mapped[int] = mapped_column(Integer)
    period_month: Mapped[int] = mapped_column(Integer)
    data_status: Mapped[str] = mapped_column(String(24), default="PENDING_IMPORT")
    matching_status: Mapped[str] = mapped_column(String(24), default="NOT_STARTED")
    filing_status: Mapped[str] = mapped_column(String(24), default="NOT_STARTED")
    report_status: Mapped[str] = mapped_column(String(24), default="NOT_STARTED")
    pending_confirmation_count: Mapped[int] = mapped_column(Integer, default=0)
    completion_percent: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(ForeignKey("monthly_work_packages.id"), index=True)
    file_type: Mapped[str] = mapped_column(String(32))
    original_filename: Mapped[str] = mapped_column(String(240))
    stored_path: Mapped[str] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String(24), default="PENDING")
    field_mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    error_rows: Mapped[list] = mapped_column(JSON, default=list)
    import_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(ForeignKey("monthly_work_packages.id"), index=True)
    import_batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    transaction_date: Mapped[date] = mapped_column(Date)
    summary: Mapped[str] = mapped_column(Text)
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    counterparty_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    counterparty_account: Mapped[str | None] = mapped_column(String(80), nullable=True)
    balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    raw_row_data: Mapped[dict] = mapped_column(JSON, default=dict)
    parse_confidence: Mapped[int] = mapped_column(Integer, default=100)
    processing_status: Mapped[str] = mapped_column(String(24), default="PENDING")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(ForeignKey("monthly_work_packages.id"), index=True)
    import_batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    invoice_direction: Mapped[str] = mapped_column(String(12))
    invoice_number: Mapped[str] = mapped_column(String(80), index=True)
    invoice_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    seller_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    buyer_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="NORMAL")
    raw_row_data: Mapped[dict] = mapped_column(JSON, default=dict)
```

Append these models to the same file:

```python
class MatchRecord(Base):
    __tablename__ = "match_records"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(ForeignKey("monthly_work_packages.id"), index=True)
    bank_transaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("bank_transactions.id"), nullable=True)
    invoice_id: Mapped[UUID | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    match_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_method: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    explanation: Mapped[str] = mapped_column(Text, default="")
    confirmation_status: Mapped[str] = mapped_column(String(24), default="AUTO_CONFIRMED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AccountingLine(Base):
    __tablename__ = "accounting_lines"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(ForeignKey("monthly_work_packages.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))
    business_type: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    include_category: Mapped[str] = mapped_column(String(32))
    confirmation_status: Mapped[str] = mapped_column(String(24), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MatchingRule(Base):
    __tablename__ = "matching_rules"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    enterprise_id: Mapped[UUID | None] = mapped_column(ForeignKey("enterprises.id"), nullable=True)
    scope: Mapped[str] = mapped_column(String(24))
    summary_keywords: Mapped[list] = mapped_column(JSON, default=list)
    counterparty_pattern: Mapped[str | None] = mapped_column(String(160), nullable=True)
    min_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    invoice_direction: Mapped[str | None] = mapped_column(String(12), nullable=True)
    suggested_business_type: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(24), default="BUILT_IN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MonthlyStatement(Base):
    __tablename__ = "monthly_statements"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(ForeignKey("monthly_work_packages.id"), index=True)
    estimated_balance_sheet: Mapped[dict] = mapped_column(JSON, default=dict)
    estimated_income_statement: Mapped[dict] = mapped_column(JSON, default=dict)
    formal_balance_sheet: Mapped[dict] = mapped_column(JSON, default=dict)
    formal_income_statement: Mapped[dict] = mapped_column(JSON, default=dict)
    difference_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TaxFilingDraft(Base):
    __tablename__ = "tax_filing_drafts"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(ForeignKey("monthly_work_packages.id"), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    export_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    monthly_work_package_id: Mapped[UUID] = mapped_column(ForeignKey("monthly_work_packages.id"), index=True)
    report_type: Mapped[str] = mapped_column(String(32))
    data_version: Mapped[dict] = mapped_column(JSON, default=dict)
    html_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    export_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="GENERATED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(index=True)
    monthly_work_package_id: Mapped[UUID | None] = mapped_column(ForeignKey("monthly_work_packages.id"), nullable=True)
    actor: Mapped[str] = mapped_column(String(80), default="system")
    action: Mapped[str] = mapped_column(String(80))
    before_data: Mapped[dict] = mapped_column(JSON, default=dict)
    after_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: Export models and initialize tables**

Create `finwise-accounting/backend/app/models/__init__.py`:

```python
from app.models.entities import (
    AccountingLine,
    AuditLog,
    BankTransaction,
    Enterprise,
    ImportBatch,
    InitialFinancialSnapshot,
    Invoice,
    MatchRecord,
    MatchingRule,
    MonthlyStatement,
    MonthlyWorkPackage,
    Organization,
    Report,
    TaxFilingDraft,
)

__all__ = [
    "AccountingLine",
    "AuditLog",
    "BankTransaction",
    "Enterprise",
    "ImportBatch",
    "InitialFinancialSnapshot",
    "Invoice",
    "MatchRecord",
    "MatchingRule",
    "MonthlyStatement",
    "MonthlyWorkPackage",
    "Organization",
    "Report",
    "TaxFilingDraft",
]
```

Modify `finwise-accounting/backend/app/main.py`:

```python
from fastapi import FastAPI

from app.core.database import Base, engine
from app import models  # noqa: F401


def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine)
    app = FastAPI(title="FinWise Accounting API")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 5: Run model tests**

Run:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
python -m pytest tests/test_enterprise_initialization.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit domain models**

```bash
git add finwise-accounting/backend
git commit -m "feat(accounting): add core domain models"
```

## Task 3: Enterprise Initialization And Monthly Package API

**Files:**
- Create: `finwise-accounting/backend/app/schemas/enterprise.py`
- Create: `finwise-accounting/backend/app/schemas/monthly.py`
- Create: `finwise-accounting/backend/app/services/enterprise_service.py`
- Create: `finwise-accounting/backend/app/api/deps.py`
- Create: `finwise-accounting/backend/app/api/enterprises.py`
- Modify: `finwise-accounting/backend/app/main.py`
- Test: `finwise-accounting/backend/tests/test_enterprise_initialization.py`

- [ ] **Step 1: Extend failing tests for services**

Append to `test_enterprise_initialization.py`:

```python
from app.services.enterprise_service import (
    create_enterprise,
    create_monthly_work_package,
    save_initial_snapshot,
)


def test_create_enterprise_initial_snapshot_and_package(db_session):
    enterprise = create_enterprise(
        db_session,
        name="苏州初始化测试有限公司",
        unified_social_credit_code="91320500INIT000001",
        taxpayer_type="GENERAL",
        industry="软件和信息技术服务业",
    )
    snapshot = save_initial_snapshot(
        db_session,
        enterprise_id=enterprise.id,
        balance_sheet_data={"资产总计": 500000, "负债合计": 120000, "所有者权益合计": 380000},
        income_statement_data={"营业收入": 200000, "净利润": 30000},
    )
    package = create_monthly_work_package(db_session, enterprise_id=enterprise.id, year=2026, month=5)

    assert snapshot.validation_result == {"balanced": True}
    assert package.data_status == "PENDING_IMPORT"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_enterprise_initialization.py -q
```

Expected: FAIL because `enterprise_service` does not exist.

- [ ] **Step 3: Implement enterprise service**

Create `finwise-accounting/backend/app/services/enterprise_service.py`:

```python
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.org_context import get_current_organization_id
from app.models import Enterprise, InitialFinancialSnapshot, MonthlyWorkPackage


def create_enterprise(
    db: Session,
    *,
    name: str,
    unified_social_credit_code: str,
    taxpayer_type: str,
    industry: str,
    province: str = "江苏省",
    city: str = "苏州市",
) -> Enterprise:
    enterprise = Enterprise(
        organization_id=get_current_organization_id(),
        name=name,
        unified_social_credit_code=unified_social_credit_code,
        taxpayer_type=taxpayer_type,
        industry=industry,
        province=province,
        city=city,
    )
    db.add(enterprise)
    db.commit()
    db.refresh(enterprise)
    return enterprise


def _is_balance_sheet_balanced(data: dict) -> bool:
    assets = float(data.get("资产总计", 0) or 0)
    liabilities = float(data.get("负债合计", 0) or 0)
    equity = float(data.get("所有者权益合计", 0) or 0)
    return abs(assets - liabilities - equity) < 0.01


def save_initial_snapshot(
    db: Session,
    *,
    enterprise_id: UUID,
    balance_sheet_data: dict,
    income_statement_data: dict,
) -> InitialFinancialSnapshot:
    organization_id = get_current_organization_id()
    snapshot = InitialFinancialSnapshot(
        organization_id=organization_id,
        enterprise_id=enterprise_id,
        balance_sheet_data=balance_sheet_data,
        income_statement_data=income_statement_data,
        validation_result={"balanced": _is_balance_sheet_balanced(balance_sheet_data)},
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def create_monthly_work_package(db: Session, *, enterprise_id: UUID, year: int, month: int) -> MonthlyWorkPackage:
    package = MonthlyWorkPackage(
        organization_id=get_current_organization_id(),
        enterprise_id=enterprise_id,
        period_year=year,
        period_month=month,
    )
    db.add(package)
    db.commit()
    db.refresh(package)
    return package
```

- [ ] **Step 4: Add schemas and routes**

Create `finwise-accounting/backend/app/schemas/enterprise.py`:

```python
from pydantic import BaseModel, Field


class EnterpriseCreate(BaseModel):
    name: str = Field(min_length=1)
    unified_social_credit_code: str = Field(min_length=6)
    taxpayer_type: str
    industry: str
    province: str = "江苏省"
    city: str = "苏州市"


class InitialSnapshotCreate(BaseModel):
    balance_sheet_data: dict
    income_statement_data: dict
```

Create `finwise-accounting/backend/app/schemas/monthly.py`:

```python
from pydantic import BaseModel, Field


class MonthlyPackageCreate(BaseModel):
    period_year: int = Field(ge=2020, le=2100)
    period_month: int = Field(ge=1, le=12)
```

Then create `api/enterprises.py` with:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.enterprise import EnterpriseCreate, InitialSnapshotCreate
from app.schemas.monthly import MonthlyPackageCreate
from app.services.enterprise_service import create_enterprise, create_monthly_work_package, save_initial_snapshot

router = APIRouter(prefix="/api/enterprises", tags=["enterprises"])


@router.post("")
def create_enterprise_endpoint(payload: EnterpriseCreate, db: Session = Depends(get_db)):
    return create_enterprise(db, **payload.model_dump())


@router.post("/{enterprise_id}/initial-snapshot")
def save_initial_snapshot_endpoint(enterprise_id: str, payload: InitialSnapshotCreate, db: Session = Depends(get_db)):
    return save_initial_snapshot(db, enterprise_id=enterprise_id, **payload.model_dump())


@router.post("/{enterprise_id}/monthly-packages")
def create_monthly_package_endpoint(enterprise_id: str, payload: MonthlyPackageCreate, db: Session = Depends(get_db)):
    return create_monthly_work_package(db, enterprise_id=enterprise_id, year=payload.period_year, month=payload.period_month)
```

- [ ] **Step 5: Register router**

Modify `main.py` to include the router:

```python
from app.api.enterprises import router as enterprises_router

app.include_router(enterprises_router)
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_enterprise_initialization.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit enterprise workflow**

```bash
git add finwise-accounting/backend
git commit -m "feat(accounting): add enterprise initialization workflow"
```

## Task 4: Import Service For Excel And CSV

**Files:**
- Create: `finwise-accounting/backend/app/services/import_service.py`
- Create: `finwise-accounting/backend/app/schemas/import_batch.py`
- Create: `finwise-accounting/backend/app/api/imports.py`
- Modify: `finwise-accounting/backend/app/main.py`
- Test: `finwise-accounting/backend/tests/test_import_service.py`

- [ ] **Step 1: Write failing import tests**

Create `test_import_service.py` with in-memory row tests:

```python
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.models import MonthlyWorkPackage
from app.services.import_service import import_bank_rows, import_invoice_rows


def make_package(db_session):
    package = MonthlyWorkPackage(
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        enterprise_id=UUID("00000000-0000-0000-0000-000000000099"),
        period_year=2026,
        period_month=5,
    )
    db_session.add(package)
    db_session.commit()
    return package


def test_import_bank_rows_maps_common_columns(db_session):
    package = make_package(db_session)
    result = import_bank_rows(
        db_session,
        monthly_work_package_id=package.id,
        rows=[{"交易日期": "2026-05-08", "摘要": "收到货款", "贷方金额": "11300.00", "对方户名": "苏州客户"}],
    )
    assert result["created"] == 1
    assert result["errors"] == []


def test_import_invoice_rows_maps_input_and_output(db_session):
    package = make_package(db_session)
    result = import_invoice_rows(
        db_session,
        monthly_work_package_id=package.id,
        direction="OUTPUT",
        rows=[{"发票号码": "0001", "开票日期": "2026/05/06", "金额": "10000", "税额": "1300", "价税合计": "11300"}],
    )
    assert result["created"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_import_service.py -q
```

Expected: FAIL because import service does not exist.

- [ ] **Step 3: Implement column mapping and row imports**

Create `import_service.py` with:

```python
from datetime import date
from decimal import Decimal
from uuid import UUID

import pandas as pd
from sqlalchemy.orm import Session

from app.core.org_context import get_current_organization_id
from app.models import BankTransaction, Invoice

BANK_COLUMNS = {
    "transaction_date": ["交易日期", "日期", "交易时间"],
    "summary": ["摘要", "交易说明", "用途", "摘要说明"],
    "debit_amount": ["借方金额", "支出金额", "借记金额"],
    "credit_amount": ["贷方金额", "收入金额", "贷记金额"],
    "balance": ["余额", "账户余额", "当前余额"],
    "counterparty_name": ["对方户名", "对手方名称", "对方账户名"],
}

INVOICE_COLUMNS = {
    "invoice_number": ["发票号码", "发票代码", "发票编码"],
    "invoice_date": ["开票日期", "日期"],
    "amount": ["金额", "不含税金额", "合计金额"],
    "tax_amount": ["税额", "税款"],
    "total_amount": ["价税合计", "总金额", "税后合计"],
    "seller_name": ["销售方名称", "销货方", "卖方名称"],
    "buyer_name": ["购买方名称", "购货方", "买方名称"],
}


def pick(row: dict, aliases: list[str], default=None):
    for alias in aliases:
        value = row.get(alias)
        if value not in (None, ""):
            return value
    return default


def to_decimal(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value).replace(",", "").replace("￥", "").strip())


def to_date(value) -> date:
    return pd.to_datetime(value).date()


def import_bank_rows(db: Session, *, monthly_work_package_id: UUID, rows: list[dict]) -> dict:
    created = 0
    errors: list[dict] = []
    for index, row in enumerate(rows, start=1):
        try:
            transaction = BankTransaction(
                organization_id=get_current_organization_id(),
                monthly_work_package_id=monthly_work_package_id,
                transaction_date=to_date(pick(row, BANK_COLUMNS["transaction_date"])),
                summary=str(pick(row, BANK_COLUMNS["summary"], "")),
                debit_amount=to_decimal(pick(row, BANK_COLUMNS["debit_amount"], "0")),
                credit_amount=to_decimal(pick(row, BANK_COLUMNS["credit_amount"], "0")),
                balance=to_decimal(pick(row, BANK_COLUMNS["balance"], "0")),
                counterparty_name=pick(row, BANK_COLUMNS["counterparty_name"]),
                raw_row_data=row,
            )
            if transaction.debit_amount == 0 and transaction.credit_amount == 0:
                raise ValueError("missing debit or credit amount")
            db.add(transaction)
            created += 1
        except Exception as exc:
            errors.append({"row": index, "error": str(exc), "raw": row})
    db.commit()
    return {"created": created, "errors": errors}


def import_invoice_rows(db: Session, *, monthly_work_package_id: UUID, direction: str, rows: list[dict]) -> dict:
    created = 0
    errors: list[dict] = []
    for index, row in enumerate(rows, start=1):
        try:
            invoice = Invoice(
                organization_id=get_current_organization_id(),
                monthly_work_package_id=monthly_work_package_id,
                invoice_direction=direction,
                invoice_number=str(pick(row, INVOICE_COLUMNS["invoice_number"])),
                invoice_date=to_date(pick(row, INVOICE_COLUMNS["invoice_date"])),
                amount=to_decimal(pick(row, INVOICE_COLUMNS["amount"])),
                tax_amount=to_decimal(pick(row, INVOICE_COLUMNS["tax_amount"])),
                total_amount=to_decimal(pick(row, INVOICE_COLUMNS["total_amount"])),
                seller_name=pick(row, INVOICE_COLUMNS["seller_name"]),
                buyer_name=pick(row, INVOICE_COLUMNS["buyer_name"]),
                raw_row_data=row,
            )
            db.add(invoice)
            created += 1
        except Exception as exc:
            errors.append({"row": index, "error": str(exc), "raw": row})
    db.commit()
    return {"created": created, "errors": errors}
```

- [ ] **Step 4: Add upload endpoints**

Create `finwise-accounting/backend/app/api/imports.py`:

```python
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.import_service import import_bank_rows, import_invoice_rows

router = APIRouter(prefix="/api/monthly-packages/{package_id}/imports", tags=["imports"])


def read_upload_rows(file: UploadFile) -> list[dict]:
    suffix = Path(file.filename or "").suffix.lower()
    with NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(file.file.read())
        tmp.flush()
        if suffix == ".csv":
            frame = pd.read_csv(tmp.name)
        else:
            frame = pd.read_excel(tmp.name)
    return frame.fillna("").to_dict(orient="records")


@router.post("/bank")
def import_bank_endpoint(package_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db)):
    return import_bank_rows(db, monthly_work_package_id=package_id, rows=read_upload_rows(file))


@router.post("/input-invoices")
def import_input_invoices_endpoint(package_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db)):
    return import_invoice_rows(db, monthly_work_package_id=package_id, direction="INPUT", rows=read_upload_rows(file))


@router.post("/output-invoices")
def import_output_invoices_endpoint(package_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db)):
    return import_invoice_rows(db, monthly_work_package_id=package_id, direction="OUTPUT", rows=read_upload_rows(file))
```

Routes:

```text
POST /api/monthly-packages/{package_id}/imports/bank
POST /api/monthly-packages/{package_id}/imports/input-invoices
POST /api/monthly-packages/{package_id}/imports/output-invoices
```

- [ ] **Step 5: Run import tests**

```bash
python -m pytest tests/test_import_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit imports**

```bash
git add finwise-accounting/backend
git commit -m "feat(accounting): import bank transactions and invoices"
```

## Task 5: Matching, Accounting Lines, And Rule Memory

**Files:**
- Create: `finwise-accounting/backend/app/rules/built_in.py`
- Create: `finwise-accounting/backend/app/services/matching_service.py`
- Create: `finwise-accounting/backend/app/api/matching.py`
- Modify: `finwise-accounting/backend/app/main.py`
- Test: `finwise-accounting/backend/tests/test_matching_service.py`

- [ ] **Step 1: Write failing matching tests**

Create tests covering exact match, unmatched transaction, and built-in rule:

```python
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.models import BankTransaction, Invoice, MonthlyWorkPackage
from app.services.matching_service import run_matching


ORG = UUID("00000000-0000-0000-0000-000000000001")
ENTERPRISE = UUID("00000000-0000-0000-0000-000000000099")


def make_package(db_session):
    package = MonthlyWorkPackage(organization_id=ORG, enterprise_id=ENTERPRISE, period_year=2026, period_month=5)
    db_session.add(package)
    db_session.commit()
    return package


def test_exact_amount_and_date_match(db_session):
    package = make_package(db_session)
    db_session.add(BankTransaction(organization_id=ORG, monthly_work_package_id=package.id, transaction_date=date(2026, 5, 8), summary="收到货款", credit_amount=Decimal("11300"), debit_amount=Decimal("0")))
    db_session.add(Invoice(organization_id=ORG, monthly_work_package_id=package.id, invoice_direction="OUTPUT", invoice_number="INV001", invoice_date=date(2026, 5, 6), amount=Decimal("10000"), tax_amount=Decimal("1300"), total_amount=Decimal("11300")))
    db_session.commit()

    result = run_matching(db_session, monthly_work_package_id=package.id)
    assert result["exact_matches"] == 1
    assert result["pending_confirmations"] == 0


def test_tax_payment_becomes_accounting_line(db_session):
    package = make_package(db_session)
    db_session.add(BankTransaction(organization_id=ORG, monthly_work_package_id=package.id, transaction_date=date(2026, 5, 12), summary="缴纳增值税", credit_amount=Decimal("0"), debit_amount=Decimal("2300")))
    db_session.commit()

    result = run_matching(db_session, monthly_work_package_id=package.id)
    assert result["rule_lines"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_matching_service.py -q
```

Expected: FAIL because matching service does not exist.

- [ ] **Step 3: Implement built-in rules**

Create `built_in.py`:

```python
BUILT_IN_RULES = [
    {"keywords": ["手续费"], "business_type": "BANK_FEE", "line_label": "银行手续费", "direction": "EXPENSE"},
    {"keywords": ["增值税", "税款", "税费"], "business_type": "TAX_PAYMENT", "line_label": "税费缴纳", "direction": "TAX"},
    {"keywords": ["工资", "薪资"], "business_type": "SALARY", "line_label": "工资薪金", "direction": "EXPENSE"},
    {"keywords": ["社保"], "business_type": "SOCIAL_INSURANCE", "line_label": "社保缴纳", "direction": "EXPENSE"},
    {"keywords": ["公积金"], "business_type": "HOUSING_FUND", "line_label": "公积金缴纳", "direction": "EXPENSE"},
    {"keywords": ["利息"], "business_type": "INTEREST", "line_label": "利息收支", "direction": "NON_OPERATING"},
    {"keywords": ["股东"], "business_type": "SHAREHOLDER_TRANSFER", "line_label": "股东往来", "direction": "NON_OPERATING"},
    {"keywords": ["服务费"], "business_type": "SERVICE_FEE", "line_label": "服务费", "direction": "EXPENSE"},
]
```

- [ ] **Step 4: Implement matching service**

Create `matching_service.py` with this public function and helper structure:

```python
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import AccountingLine, BankTransaction, Invoice, MatchRecord, MonthlyWorkPackage
from app.rules.built_in import BUILT_IN_RULES


def amount_for_direction(transaction: BankTransaction, invoice: Invoice) -> Decimal:
    return transaction.credit_amount if invoice.invoice_direction == "OUTPUT" else transaction.debit_amount


def days_between(left: date, right: date) -> int:
    return abs((left - right).days)


def apply_built_in_rule(transaction: BankTransaction) -> dict | None:
    summary = transaction.summary or ""
    for rule in BUILT_IN_RULES:
        if any(keyword in summary for keyword in rule["keywords"]):
            return rule
    return None


def run_matching(db: Session, *, monthly_work_package_id: UUID) -> dict:
    transactions = db.query(BankTransaction).filter_by(monthly_work_package_id=monthly_work_package_id).all()
    invoices = db.query(Invoice).filter_by(monthly_work_package_id=monthly_work_package_id).all()
    used_transaction_ids: set[UUID] = set()
    used_invoice_ids: set[UUID] = set()
    exact_matches = 0
    rule_lines = 0

    for transaction in transactions:
        for invoice in invoices:
            if transaction.id in used_transaction_ids or invoice.id in used_invoice_ids:
                continue
            if amount_for_direction(transaction, invoice) == invoice.total_amount and days_between(transaction.transaction_date, invoice.invoice_date) <= 7:
                db.add(MatchRecord(
                    organization_id=transaction.organization_id,
                    monthly_work_package_id=monthly_work_package_id,
                    bank_transaction_id=transaction.id,
                    invoice_id=invoice.id,
                    match_method="AUTO_EXACT",
                    confidence=95,
                    explanation="金额一致且日期在7天内",
                    confirmation_status="AUTO_CONFIRMED",
                ))
                used_transaction_ids.add(transaction.id)
                used_invoice_ids.add(invoice.id)
                exact_matches += 1
                break

    for transaction in transactions:
        if transaction.id in used_transaction_ids:
            continue
        rule = apply_built_in_rule(transaction)
        if not rule:
            continue
        amount = transaction.debit_amount or transaction.credit_amount
        db.add(AccountingLine(
            organization_id=transaction.organization_id,
            monthly_work_package_id=monthly_work_package_id,
            source_type="BANK_TRANSACTION",
            source_id=str(transaction.id),
            business_type=rule["business_type"],
            direction=rule["direction"],
            amount=amount,
            tax_amount=Decimal("0"),
            include_category=rule["direction"],
            confirmation_status="PENDING",
        ))
        rule_lines += 1

    package = db.get(MonthlyWorkPackage, monthly_work_package_id)
    pending = len(transactions) + len(invoices) - exact_matches * 2
    if package:
        package.pending_confirmation_count = max(0, pending)
        package.matching_status = "PENDING_CONFIRMATION" if pending else "CONFIRMED"
    db.commit()
    return {"exact_matches": exact_matches, "rule_lines": rule_lines, "pending_confirmations": max(0, pending)}
```

- [ ] **Step 5: Add confirmation API**

Routes:

```text
POST /api/monthly-packages/{package_id}/matching/run
POST /api/matches/{match_id}/confirm
POST /api/accounting-lines/{line_id}/confirm
```

Confirmation writes an `AuditLog` row.

- [ ] **Step 6: Run matching tests**

```bash
python -m pytest tests/test_matching_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit matching**

```bash
git add finwise-accounting/backend
git commit -m "feat(accounting): add matching and confirmation workflow"
```

## Task 6: Statements, Tax Filing Draft, And Exports

**Files:**
- Create: `finwise-accounting/backend/app/services/statement_service.py`
- Create: `finwise-accounting/backend/app/services/tax_service.py`
- Create: `finwise-accounting/backend/app/api/statements.py`
- Create: `finwise-accounting/backend/app/api/tax.py`
- Test: `finwise-accounting/backend/tests/test_statement_and_tax.py`

- [ ] **Step 1: Write failing tests**

Test expected behavior:

```python
from decimal import Decimal

from app.services.tax_service import calculate_vat_draft


def test_calculate_vat_draft_from_invoice_totals():
    draft = calculate_vat_draft(
        output_amount=Decimal("100000"),
        output_tax=Decimal("13000"),
        input_amount=Decimal("40000"),
        input_tax=Decimal("5200"),
    )
    assert draft["vat_payable"] == Decimal("7800")
    assert draft["surcharge_estimate"] == Decimal("936.00")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_statement_and_tax.py -q
```

Expected: FAIL because tax service does not exist.

- [ ] **Step 3: Implement statement estimate**

Create `statement_service.py`:

- Revenue = confirmed output invoice amount.
- Output tax = confirmed output invoice tax.
- Cost baseline = confirmed input invoice amount.
- Expenses = confirmed accounting lines with expense direction.
- Cash movement = bank credit total minus bank debit total.
- Formal statements, when uploaded, are stored separately and used for comparison.

- [ ] **Step 4: Implement tax draft**

Create `tax_service.py`:

```python
from decimal import Decimal, ROUND_HALF_UP


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_vat_draft(*, output_amount: Decimal, output_tax: Decimal, input_amount: Decimal, input_tax: Decimal) -> dict:
    vat_payable = max(Decimal("0"), output_tax - input_tax)
    surcharge_estimate = money(vat_payable * Decimal("0.12"))
    return {
        "output_amount": money(output_amount),
        "output_tax": money(output_tax),
        "input_amount": money(input_amount),
        "input_tax": money(input_tax),
        "vat_payable": money(vat_payable),
        "surcharge_estimate": surcharge_estimate,
    }
```

- [ ] **Step 5: Implement Excel export**

Use openpyxl to create a workbook with copyable rows:

```text
字段, 金额, 说明
销项销售额, 100000.00, 本期销项不含税销售额
销项税额, 13000.00, 本期销项税额
进项金额, 40000.00, 本期进项不含税金额
进项税额, 5200.00, 本期可抵扣进项税额
本期应纳增值税, 7800.00, 销项税额减进项税额
附加税估算, 936.00, 按12%估算
异常提醒, 未匹配发票2张, 导出前请人工核对
```

- [ ] **Step 6: Run statement and tax tests**

```bash
python -m pytest tests/test_statement_and_tax.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit statements and tax**

```bash
git add finwise-accounting/backend
git commit -m "feat(accounting): generate statements and filing drafts"
```

## Task 7: Reports And Privacy Guard

**Files:**
- Create: `finwise-accounting/backend/app/reports/monthly_brief.py`
- Create: `finwise-accounting/backend/app/reports/health_diagnosis.py`
- Create: `finwise-accounting/backend/app/services/report_service.py`
- Create: `finwise-accounting/backend/app/api/reports.py`
- Test: `finwise-accounting/backend/tests/test_reports_and_privacy.py`

- [ ] **Step 1: Write failing report tests**

Create tests:

```python
from app.reports.monthly_brief import render_monthly_brief_html
from app.services.report_service import desensitize_ai_payload


def test_monthly_brief_contains_owner_facing_sections():
    html = render_monthly_brief_html(
        enterprise_name="苏州样例科技有限公司",
        period="2026-05",
        summary={"revenue": 100000, "expense": 60000, "cash_net": 20000, "tax_payable": 7800},
        exceptions=[{"label": "未匹配流水", "count": 2}],
    )
    assert "本月经营概览" in html
    assert "现金流提醒" in html
    assert "下月建议" in html


def test_ai_payload_masks_sensitive_names_and_tax_numbers():
    payload = desensitize_ai_payload(
        {
            "enterprise_name": "苏州样例科技有限公司",
            "tax_number": "91320500INIT000001",
            "counterparty_name": "苏州重要客户有限公司",
            "summary": "收到苏州重要客户货款",
            "amount": "11300.00",
        }
    )
    assert "苏州样例科技有限公司" not in str(payload)
    assert "91320500INIT000001" not in str(payload)
    assert payload["counterparty_name"] == "苏州***公司"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_reports_and_privacy.py -q
```

Expected: FAIL because report modules do not exist.

- [ ] **Step 3: Implement monthly brief HTML**

Create owner-readable HTML sections:

```text
本月经营概览
税务概览
异常事项
现金流提醒
下月建议
```

Use monetary amounts in yuan for monthly brief and in 万元 for full health diagnosis.

- [ ] **Step 4: Implement full diagnosis skeleton**

Create sections:

```text
执行摘要与关键结论
企业概况
偿债能力
盈利能力
运营效率与现金流
税务风险
风险量化
建议
```

When data is insufficient, return a report status of `DATA_INSUFFICIENT` with clear missing-data messages.

- [ ] **Step 5: Implement privacy guard**

`desensitize_ai_payload` must:

- Remove enterprise name.
- Remove tax number.
- Mask counterparty names to first two Chinese characters plus `***公司` when possible.
- Preserve amount, direction, date distance, and non-identifying summary fragments.

- [ ] **Step 6: Run report tests**

```bash
python -m pytest tests/test_reports_and_privacy.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit reports**

```bash
git add finwise-accounting/backend
git commit -m "feat(accounting): generate reports with privacy guard"
```

## Task 8: Frontend UI Foundation

**Files:**
- Create: `finwise-accounting/frontend/src/styles/tokens.css`
- Create: `finwise-accounting/frontend/src/styles/base.css`
- Create: `finwise-accounting/frontend/src/components/AppLayout.vue`
- Create: `finwise-accounting/frontend/src/components/StatusTag.vue`
- Create: `finwise-accounting/frontend/src/components/MetricCard.vue`
- Create: `finwise-accounting/frontend/src/components/DataTableShell.vue`
- Create: router and store

- [ ] **Step 1: Create design tokens**

Create `tokens.css`:

```css
:root {
  --fw-bg: #f6f8fb;
  --fw-surface: #ffffff;
  --fw-surface-muted: #f1f5f9;
  --fw-ink: #172033;
  --fw-ink-soft: #48566f;
  --fw-ink-muted: #718096;
  --fw-line: #d9e2ef;
  --fw-line-strong: #bcc9d8;
  --fw-brand: #1769e0;
  --fw-brand-dark: #0f4ba8;
  --fw-brand-soft: #e8f1ff;
  --fw-success: #16855c;
  --fw-success-soft: #e8f7ef;
  --fw-warning: #b56a12;
  --fw-warning-soft: #fff3df;
  --fw-danger: #c24136;
  --fw-danger-soft: #fff0ee;
  --fw-radius: 8px;
  --fw-radius-sm: 6px;
  --fw-font: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
```

- [ ] **Step 2: Create base layout CSS**

Create `base.css` with body background, font, table numeric styling, and utility classes `.amount`, `.page-title`, `.section-title`, `.caption`.

- [ ] **Step 3: Create AppLayout**

Left navigation items:

```text
工作台
企业名册
月度工作包
账目明细
申报辅助
输出中心
规则设置
```

Topbar primary button: `创建本月工作包`.

- [ ] **Step 4: Create StatusTag component**

Map statuses:

```javascript
const statusMap = {
  PENDING_IMPORT: ['待导入', 'warning'],
  PENDING_CONFIRMATION: ['待确认', 'warning'],
  CONFIRMED: ['已确认', 'success'],
  READY_TO_EXPORT: ['可导出', 'primary'],
  EXPORTED: ['已导出', 'info'],
  DATA_INSUFFICIENT: ['数据不足', 'danger'],
}
```

- [ ] **Step 5: Create MetricCard and DataTableShell**

Metric cards follow the UI spec: label row, 24px bold value, 12px subtext. Data table shell wraps Element Plus tables with filters and a single main action.

- [ ] **Step 6: Build frontend**

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run build
```

Expected: PASS.

- [ ] **Step 7: Commit UI foundation**

```bash
git add finwise-accounting/frontend
git commit -m "feat(accounting): add UI foundation"
```

## Task 9: Frontend Core Views

**Files:**
- Create: `EnterpriseListView.vue`
- Create: `EnterpriseInitView.vue`
- Create: `MonthlyWorkspaceView.vue`
- Create: `AccountDetailsView.vue`
- Create: `OutputCenterView.vue`
- Modify: router/store/API client

- [ ] **Step 1: Implement API client**

Create axios client with base URL `/api`, and methods for enterprises, packages, imports, matching, statements, tax, and reports.

- [ ] **Step 2: Implement EnterpriseListView**

Show:

- Enterprise name.
- Taxpayer type.
- Latest month.
- Data status.
- Pending confirmations.
- Latest report status.

Main action: `新增企业`.

- [ ] **Step 3: Implement EnterpriseInitView**

Sections:

- 基础信息.
- 期初资产负债表.
- 期初利润表.
- 校验结果.

Use upload controls and validation status cards.

- [ ] **Step 4: Implement MonthlyWorkspaceView**

Use step cards:

```text
导入资料 -> 解析结果 -> 匹配确认 -> 账目明细 -> 预估报表 -> 申报辅助 -> 老板简报
```

Show missing data checklist and pending confirmation count.

- [ ] **Step 5: Implement AccountDetailsView**

Tabs:

- 流水视图.
- 发票视图.
- 待确认清单.

Rows show match status, confidence, business type, amount, tax amount, and action buttons.

- [ ] **Step 6: Implement OutputCenterView**

Cards:

- 申报辅助 Excel.
- 老板版月度简报.
- 完整健康诊断报告.

Full diagnosis card disabled with `数据不足` if prerequisites are missing.

- [ ] **Step 7: Build frontend**

```bash
npm run build
```

Expected: PASS.

- [ ] **Step 8: Commit core views**

```bash
git add finwise-accounting/frontend
git commit -m "feat(accounting): add monthly work package views"
```

## Task 10: End-To-End Verification And Audit

**Files:**
- Create: `finwise-accounting/backend/tests/test_end_to_end_monthly_flow.py`
- Create: `finwise-accounting/docs/audit/phase1-audit.md`

- [ ] **Step 1: Write backend end-to-end test**

Test flow:

```text
create enterprise
save initial snapshot
create monthly package
import bank row
import output invoice row
run matching
generate tax draft
render monthly brief
```

Expected:

- One exact match.
- VAT payable equals output tax minus input tax.
- Monthly brief contains owner-facing sections.

- [ ] **Step 2: Run backend tests**

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run build
```

Expected: PASS.

- [ ] **Step 4: Start local servers**

Backend:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Frontend:

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm run dev -- --port 5174
```

Expected:

- Backend health at `http://127.0.0.1:8001/health`.
- Frontend at `http://127.0.0.1:5174`.

- [ ] **Step 5: Browser verification**

Use Browser or Playwright to verify:

- Enterprise list renders.
- Monthly workspace renders.
- Account detail tabs render.
- Output center renders.
- No obvious text overlap at desktop width.
- UI uses the approved token palette and restrained backend style.

- [ ] **Step 6: Audit old code isolation**

Run:

```bash
git diff --name-only HEAD -- backend frontend
```

Expected: no files from root `backend/` or root `frontend/` caused by this rebuild plan's implementation.

- [ ] **Step 7: Write audit note**

Create `finwise-accounting/docs/audit/phase1-audit.md`:

```markdown
# Phase 1 Audit

## Verification

- Backend tests:
- Frontend build:
- Browser check:

## Privacy

- AI payloads exclude enterprise names:
- AI payloads exclude tax numbers:
- Counterparty names are masked:

## Scope

- Old backend/frontend untouched:
- No direct tax bureau submission:
- No full voucher/general ledger replacement:

## Remaining Risks

- PDF bank statement parsing:
- Exact Jiangsu electronic tax bureau import compatibility:
- More bank and invoice templates:
```

- [ ] **Step 8: Commit audit**

```bash
git add finwise-accounting
git commit -m "test(accounting): verify monthly workflow"
```

## Self-Review Checklist

- Every task writes only under `finwise-accounting/`, except plan/spec docs.
- Backend services have tests before implementation.
- Import, matching, tax, and privacy risks are each covered by tests.
- Frontend follows the provided UI reference tokens and table-first backend style.
- The plan does not require full accounting vouchers, tax bureau submission, or cross-enterprise rule sharing.
- The old root `backend/` and `frontend/` directories remain untouched.
