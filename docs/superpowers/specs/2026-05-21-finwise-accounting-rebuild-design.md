# FinWise Accounting Rebuild Design

Date: 2026-05-21
Status: Approved design draft
Target directory: `finwise-accounting/`

## 1. Purpose

This rebuild creates a new system for Suzhou-area bookkeeping agencies. The goal is to reduce monthly repetitive work around client data collection, bank/invoice reconciliation, tax filing preparation, and customer-facing financial reporting.

The new project must be developed in `finwise-accounting/`. The existing `backend/` and `frontend/` directories are reference-only and must not be modified for this rebuild.

## 2. Product Positioning

The first release is a monthly data collation and filing assistance system. It is not a full accounting automation system and does not replace a formal bookkeeping ledger.

The system helps a bookkeeping agency:

- Maintain enterprise information.
- Initialize each enterprise with opening financial statements.
- Import monthly bank transactions, input invoice details, and output invoice details.
- Match bank transactions and invoices.
- Let users confirm unresolved or ambiguous matches.
- Reuse confirmed rules for the same enterprise in later months.
- Generate monthly account detail views.
- Generate estimated monthly balance sheet and income statement.
- Compare estimated statements with optionally uploaded formal statements.
- Generate Jiangsu VAT and surcharge filing assistance Excel.
- Generate a boss-facing monthly financial brief.
- Generate a fuller financial health diagnosis when data is sufficient.

## 3. Explicit Non-Goals For Phase 1

Phase 1 will not build:

- A complete voucher, general ledger, or sub-ledger replacement.
- Fully automatic accounting entries.
- Direct electronic tax bureau submission.
- Cross-enterprise or bookkeeping-agency-level shared rule learning.
- Enterprise customer self-service portals.
- Financing product matching.
- Tax planning, project application, or loan-after-risk modules.

## 4. Core Product Object Model

The main product flow is:

```text
Enterprise -> Initial Financial Snapshot -> Monthly Work Package
```

The monthly work package is the core operating object. Users should work by enterprise and month, not by scattered feature pages.

## 5. User Flow

1. Create or select an enterprise.
2. Complete enterprise initialization:
   - Basic enterprise profile.
   - Opening balance sheet.
   - Opening income statement.
3. Create a monthly work package.
4. Import minimum monthly data:
   - Bank transactions.
   - Input invoice details.
   - Output invoice details.
5. Optionally import formal monthly balance sheet and formal income statement.
6. System parses and normalizes imported files.
7. System matches bank transactions and invoices.
8. User reviews unresolved or ambiguous items.
9. User confirms account detail classifications and saves enterprise-specific rules where useful.
10. System generates account detail views.
11. System generates estimated monthly financial statements.
12. System compares estimated statements with formal statements when available.
13. System generates tax filing assistance Excel.
14. System generates a boss-facing monthly brief.
15. System generates a full financial health diagnosis when enough data exists.

## 6. Core Pages

### 6.1 Enterprise List

Shows enterprises managed by the bookkeeping agency. Key fields:

- Enterprise name.
- Taxpayer type.
- Latest processed month.
- Monthly data status.
- Pending confirmation count.
- Latest report status.

Primary actions:

- Create enterprise.
- Open enterprise.
- Create current monthly work package.

### 6.2 Enterprise Initialization

Required before monthly processing. Captures:

- Basic enterprise information.
- Opening balance sheet import.
- Opening income statement import.

The system validates:

- Whether the balance sheet balances.
- Whether key income statement fields are recognized.
- Whether required enterprise fields are present.

### 6.3 Monthly Work Package Dashboard

The main work area for each enterprise and month. It shows:

- Enterprise and month.
- Processing progress.
- Missing data checklist.
- Import status.
- Parse status.
- Matching status.
- Pending confirmation count.
- Statement status.
- Filing draft status.
- Report status.

The dashboard organizes the workflow into:

1. Import data.
2. Review parsed results.
3. Confirm matches.
4. Review account details.
5. Generate statements.
6. Generate tax filing assistance.
7. Generate reports.

### 6.4 Account Details

Provides two views over the same data:

- Bank transaction view: default working view for reconciliation.
- Invoice view: tax and payment tracking view.

The page also provides a pending confirmation list for:

- Unmatched bank transactions.
- Unmatched invoices.
- Ambiguous match candidates.
- First-time rule hits.
- Low-confidence AI suggestions.

### 6.5 Rule Confirmation

When users confirm unresolved items, they may save enterprise-specific rules. Phase 1 supports:

- Built-in common rules.
- Enterprise-specific rules.

Phase 1 does not support bookkeeping-agency-level shared rules.

### 6.6 Output Center

Outputs are grouped under the monthly work package:

- Jiangsu VAT and surcharge filing assistance Excel.
- Boss-facing monthly financial brief.
- Full financial health diagnosis report when data is sufficient.

## 7. Data Model

All business records must include `organization_id`. All monthly records must include `monthly_work_package_id` where applicable. Original files and original row data must be retained for traceability.

### 7.1 Organization

Represents the bookkeeping agency. Phase 1 may use a default organization, but the model must preserve this boundary.

### 7.2 Enterprise

Represents a client enterprise.

Key fields:

- `organization_id`
- `name`
- `unified_social_credit_code`
- `taxpayer_type`
- `industry`
- `province`
- `city`
- `status`

### 7.3 InitialFinancialSnapshot

Stores opening statement data and import evidence:

- Opening balance sheet structured data.
- Opening income statement structured data.
- Original files.
- Recognition status.
- Validation results.

### 7.4 MonthlyWorkPackage

Core monthly operating object.

Key fields:

- `organization_id`
- `enterprise_id`
- `period_year`
- `period_month`
- `data_status`
- `matching_status`
- `filing_status`
- `report_status`
- `pending_confirmation_count`
- `completion_percent`

### 7.5 ImportBatch

One uploaded file creates one import batch.

Supported batch types:

- Bank transactions.
- Input invoices.
- Output invoices.
- Formal balance sheet.
- Formal income statement.

The batch stores:

- Original file path.
- File type.
- Parse status.
- Field mapping.
- Error rows.
- Import summary.

### 7.6 BankTransaction

Represents one bank transaction row.

Key fields:

- Transaction date.
- Summary.
- Debit amount.
- Credit amount.
- Counterparty name.
- Counterparty account.
- Balance.
- Raw row data.
- Parse confidence.
- Processing status.

### 7.7 Invoice

Represents one input or output invoice row.

Key fields:

- Invoice direction: input or output.
- Invoice number.
- Invoice date.
- Amount.
- Tax amount.
- Total amount.
- Seller name.
- Buyer name.
- Void or red-letter status.
- Raw row data.

### 7.8 MatchRecord

Represents a relationship between bank transactions and invoices.

It must support:

- One bank transaction to one invoice.
- One bank transaction to multiple invoices.
- Multiple bank transactions to one invoice.

Key fields:

- Match method: exact automatic, fuzzy automatic, rule hit, manual confirmation, manual exclusion.
- Confidence.
- Explanation.
- Confirmation status.

### 7.9 AccountingLine

Represents a monthly account detail line, not a formal accounting voucher.

Sources may include:

- Confirmed match records.
- Unmatched bank transactions.
- Unmatched invoices.

Key fields:

- Business type.
- Direction.
- Amount.
- Tax amount.
- Whether included in revenue, cost, expense, tax, or non-operating flow.
- Confirmation status.

### 7.10 MatchingRule

Supports rule memory.

Rule scopes:

- Built-in common rule.
- Enterprise-specific rule.

Key fields:

- Summary keywords.
- Counterparty name pattern.
- Amount range.
- Invoice direction.
- Suggested business type.
- Applicable enterprise.
- Source: built-in or user-confirmed.

### 7.11 MonthlyStatement

Stores:

- System-estimated balance sheet.
- System-estimated income statement.
- Optional formal balance sheet.
- Optional formal income statement.
- Difference comparison.

If formal statements exist, exported reports should prefer formal statement figures.

### 7.12 TaxFilingDraft

Stores Jiangsu VAT and surcharge filing assistance data.

Status values:

- Draft.
- Confirmed.
- Exported.

This status does not mean the tax bureau filing has been submitted.

### 7.13 Report

Report types:

- Boss-facing monthly brief.
- Full financial health diagnosis.

Reports store:

- Data version used.
- HTML output path.
- PDF or exported file path.
- Generation status.

## 8. Matching And Confirmation Logic

Matching runs in four layers.

### 8.1 Deterministic Matching

High-confidence automatic matching when:

- Amounts are equal.
- Dates are close.
- Counterparty name or summary text indicates a relationship.

Example: output invoice total equals a bank credit amount within seven days.

### 8.2 Combination Matching

Supports:

- One payment matching multiple invoices.
- Multiple payments matching one invoice.

Phase 1 limits candidate set size, for example to at most five items. Combination matches must be confirmed by a user before becoming final.

### 8.3 Rule Hits

Built-in rules identify common transactions:

- Bank fees.
- Tax payments.
- Social insurance and housing fund.
- Interest.
- Salaries.

Enterprise-specific rules reuse prior user confirmations.

### 8.4 AI-Assisted Suggestions

AI may suggest classifications or candidate matches, but must not directly finalize results.

Data sent to AI must be desensitized:

- Do not send enterprise names.
- Do not send tax numbers.
- Do not send full counterparty names.
- Only send safe summary fragments, amount direction, date distance, candidate type, and similar non-identifying context.

AI returns:

- Suggested business type.
- Suggested match reason.
- Confidence.

## 9. Manual Confirmation Actions

Users may:

- Accept a match.
- Change matched objects.
- Mark as no-invoice revenue.
- Mark as no-invoice expense.
- Mark as temporarily unresolved.
- Mark as non-operating transfer.
- Save as an enterprise-specific rule.

Every confirmation writes an audit record:

- User.
- Time.
- Original system suggestion.
- Final user decision.

## 10. Statement And Filing Outputs

### 10.1 Monthly Statements

The system generates estimated monthly balance sheet and income statement based on:

- Opening statements.
- Current-month bank transactions.
- Current-month input and output invoices.
- Confirmed account details.

Estimated statements are for management and comparison. They do not replace the formal bookkeeping ledger.

If formal monthly statements are uploaded, the system compares key differences:

- Revenue.
- Cost.
- Expenses.
- Tax amount.
- Receivables and payables.
- Cash balance.

Reports should prefer formal figures when formal statements are available.

### 10.2 Filing Assistance

The system exports a Jiangsu VAT and surcharge filing assistance Excel with:

- Output sales amount.
- Output tax amount.
- Input amount.
- Input tax amount.
- Deductible amount.
- VAT payable.
- Surcharge estimate.
- Exception notes.

The system does not submit filings to the electronic tax bureau.

## 11. Reports

### 11.1 Boss-Facing Monthly Brief

Generated by default each month. It is written for enterprise owners.

Sections:

- Monthly business overview.
- Revenue, expense, estimated profit, and net cash movement.
- Tax overview.
- Unmatched transaction and invoice exceptions.
- Large spending or large uncollected payment warnings.
- Cash flow reminders.
- Next-month action suggestions.

### 11.2 Full Financial Health Diagnosis

Generated when sufficient data exists. It follows the referenced financial-health-report skill at a simplified, owner-readable level.

Sections:

1. Executive summary and key conclusions.
2. Company overview.
3. Solvency analysis.
4. Profitability analysis.
5. Operational efficiency and cash flow.
6. Tax risk analysis.
7. Risk quantification.
8. Recommendations.

Professional metrics must be translated into plain business language.

## 12. Technical Architecture

The rebuild uses the original planned stack:

- Frontend: Vue 3, Element Plus, ECharts.
- Backend: FastAPI.
- Database: PostgreSQL.
- File storage: local disk in Phase 1.
- AI: pluggable domestic model integration, with rules usable before AI is enabled.
- Deployment: single ECS instance.

Suggested directory structure:

```text
finwise-accounting/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── rules/
│   │   └── reports/
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── views/
│   │   ├── components/
│   │   ├── stores/
│   │   └── router/
│   └── package.json
├── docs/
│   ├── product/
│   ├── data-samples/
│   └── decisions/
└── README.md
```

## 13. Implementation Milestones

### Milestone 1: Foundation And Enterprise Initialization

Create the isolated project, backend and frontend skeletons, enterprise management, and initialization statement imports.

Acceptance:

- New code exists only under `finwise-accounting/`.
- Enterprises can be created.
- Opening balance sheet and income statement can be imported.
- Initialization validation is visible.

### Milestone 2: Monthly Work Package And Data Import

Create monthly work packages and import bank transactions, input invoices, and output invoices.

Acceptance:

- Users can create an enterprise-month work package.
- Three required monthly file types can be imported.
- Field mapping and parse errors are visible.
- Original files and raw rows are retained.

### Milestone 3: Matching And Manual Confirmation

Build matching, pending confirmation, account detail views, and enterprise-specific rule memory.

Acceptance:

- Deterministic matches are generated.
- Ambiguous matches are sent to confirmation.
- Users can accept, edit, exclude, or classify items.
- Enterprise-specific rules can be saved and reused.

### Milestone 4: Filing Assistance And Monthly Statements

Build estimated statements, formal statement comparison, and filing assistance export.

Acceptance:

- Estimated balance sheet and income statement can be generated.
- Formal statements can be uploaded and compared.
- Jiangsu VAT and surcharge filing assistance Excel can be exported.

### Milestone 5: Reports, Testing, And Audit

Build monthly brief, full diagnosis report, tests, end-to-end checks, and code/product audit.

Acceptance:

- Monthly boss-facing brief can be generated.
- Full diagnosis report can be generated when data is sufficient.
- Core backend services have tests.
- Frontend core flows are verified.
- Sensitive data is not sent to AI.
- Old `backend/` and `frontend/` directories remain untouched.

## 14. Testing Focus

Testing must cover:

- Import tolerance for different Excel/PDF formats.
- Amount, date, tax amount, and direction parsing.
- Matching accuracy and explainability.
- Manual correction and audit records.
- Rule reuse behavior.
- Statement and filing calculation consistency.
- Report generation with insufficient and sufficient data.
- AI desensitization.
- Isolation from old project directories.

## 15. Phase 1 Implementation Assumptions

These assumptions make the first implementation plan concrete:

- Built-in matching rules first cover bank fees, tax payments, salary, social insurance, housing fund, interest income or expense, shareholder transfers, and common service-fee payments.
- Jiangsu filing assistance export first uses an internal Excel template with clear copyable fields for output sales, output tax, input amount, input tax, deductible input tax, VAT payable, surcharge base, and surcharge estimate. Exact electronic tax bureau import compatibility is not required in Phase 1.
- Excel and CSV imports are required first. PDF bank statement parsing is optional after Excel/CSV import, matching, and confirmation are stable.
- The boss-facing monthly brief first includes four charts: revenue and expense comparison, cash inflow and outflow, tax overview, and unmatched item summary.
