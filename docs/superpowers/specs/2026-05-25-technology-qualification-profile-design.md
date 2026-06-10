# Enterprise Technology Qualification Profile Design

Date: 2026-05-25
Status: Draft for user review
Target project: `finwise-accounting/`

## 1. Purpose

FinWise needs a repeatable way to scan client enterprises for government-recognized technology qualifications, intellectual property assets, and related service opportunities. These tags will be used by both bookkeeping agencies and banks, and will later become one dimension in loan scoring.

The feature should not be part of the monthly bookkeeping workflow. It belongs to enterprise master data and should be available from the enterprise roster and enterprise detail pages.

## 2. Recommended Approach

Use a hybrid design:

- FinWise stores, displays, audits, and later scores technology qualification data.
- A Codex skill performs semi-automated data collection from authenticated external platforms.

The external collection skill may use Tianyancha or Qichacha. These platforms require login and may have verification or rate limits, so FinWise should not embed account credentials or run unattended scraping from the backend.

## 3. External Data Sources

Supported sources for the first version:

- Tianyancha
- Qichacha

The collection layer should abstract the source as a provider. A scan result must record which provider produced the data.

Do not send account passwords through chat or persist them in the repository. Testing should prefer an already logged-in local browser session. If credentials are ever needed, they should be kept in local environment variables, system keychain storage, or another local secret store that is not committed and not echoed in logs.

## 4. Tags To Capture

The initial tag catalog comes from `/Volumes/共享文件夹/财务项目/获取企业标签以及服务能力增补.xlsx`.

### 4.1 Technology Qualification Tags

- 科技型中小企业
- 创新型中小企业
- 高新技术企业
- 专精特新中小企业
- 专精特新“小巨人”企业
- Other technology qualification tags discovered on the source platform

### 4.2 Intellectual Property Assets

- 软件著作权
- 实用新型专利
- 发明专利
- 集成电路布图设计
- 商标
- Other intellectual property records discovered on the source platform

The system should store counts first. When reliable details are available, it may also store item-level evidence such as title, application number, authorization date, and status.

### 4.3 Service Opportunity Tags

These tags help bookkeeping agencies identify follow-up services:

- 国家高新技术企业申报
- 国家级科技型中小企业入库
- 专精特新中小企业申报
- 创新型中小企业申报
- 省级专精特新小巨人申报
- 知识产权补充与维护
- 体系认证机会

Service opportunity tags should be derived from captured evidence and local rules, not treated as source facts unless the source explicitly states the qualification.

## 5. Data Model

Add enterprise-level technology profile records, separate from monthly work packages.

### 5.1 TechnologyProfile

Represents the latest technology qualification profile for one enterprise.

Key fields:

- `organization_id`
- `enterprise_id`
- `overall_status`: `NOT_SCANNED`, `SCANNED_PENDING_REVIEW`, `CONFIRMED`, `NEEDS_RESCAN`, `FAILED`
- `primary_provider`: `TIANYANCHA`, `QICHACHA`, or `MIXED`
- `last_scanned_at`
- `last_confirmed_at`
- `next_rescan_at`
- `summary`
- `raw_snapshot`

### 5.2 TechnologyTag

Represents one tag, asset count, or service opportunity.

Key fields:

- `organization_id`
- `enterprise_id`
- `profile_id`
- `category`: `TECH_QUALIFICATION`, `INTELLECTUAL_PROPERTY`, `CERTIFICATION`, `SERVICE_OPPORTUNITY`, `RISK_SIGNAL`
- `name`
- `status`: `HIT`, `NOT_HIT`, `PENDING_REVIEW`, `UNKNOWN`
- `value`: optional numeric or text value, such as patent count
- `confidence`: 0-100
- `source_provider`
- `source_url`
- `evidence_text`
- `evidence_file_path`: optional screenshot or exported evidence file
- `confirmed_by`
- `confirmed_at`

### 5.3 TechnologyScanJob

Tracks batch scans started by Codex or by a future system action.

Key fields:

- `organization_id`
- `provider`
- `status`: `PENDING`, `RUNNING`, `COMPLETED`, `PARTIAL_FAILED`, `FAILED`
- `target_enterprise_count`
- `completed_enterprise_count`
- `failed_enterprise_count`
- `started_at`
- `completed_at`
- `error_summary`

## 6. Codex Skill Workflow

The Codex skill should:

1. Read enterprises that are `NOT_SCANNED`, `NEEDS_RESCAN`, or explicitly selected by the user.
2. Use the user's logged-in browser session for Tianyancha or Qichacha.
3. Search each enterprise by full name and, when available, unified social credit code.
4. Extract technology qualifications, intellectual property counts, and visible evidence.
5. Normalize provider-specific names into the FinWise tag catalog.
6. Mark uncertain matches as `PENDING_REVIEW`.
7. Write structured results back to FinWise through an API.
8. Produce a scan summary listing completed, failed, and ambiguous enterprises.

The skill should be resumable. If a platform interrupts with login, captcha, or rate limits, it should stop safely and keep already collected results.

## 7. FinWise Product UI

### 7.1 Enterprise Roster

Add columns or compact badges:

- 科技画像状态
- 关键资质 tags, such as 高企, 科小, 专精特新
- 知识产权 summary, such as 发明专利 3 / 软著 5
- 最近扫描时间

### 7.2 Enterprise Detail

Add a `科技资质画像` section:

- Profile status and last scan time
- Technology qualification tags
- Intellectual property counts
- Service opportunity tags
- Evidence and provider source
- Manual confirm or reject controls for pending tags

### 7.3 Future Loan Scoring Integration

The first version should not implement loan scoring, but the data must be structured for future scoring.

Example future scoring dimensions:

- 高新技术企业 qualification
- 科技型中小企业 qualification
- 专精特新 qualification
- Invention patent count
- Software copyright count
- Recently confirmed qualification status
- Freshness of source data

Unconfirmed or stale tags should receive reduced scoring weight.

## 8. APIs

Add APIs under an enterprise-level namespace:

- `GET /api/enterprises/{enterprise_id}/technology-profile`
- `POST /api/enterprises/{enterprise_id}/technology-profile/scan-results`
- `POST /api/technology-scan-jobs`
- `GET /api/technology-scan-jobs/{job_id}`
- `POST /api/technology-tags/{tag_id}/confirm`
- `POST /api/technology-tags/{tag_id}/reject`

The scan result API is intended for Codex skill output and future provider adapters.

## 9. Security And Compliance Boundaries

- Do not store Tianyancha or Qichacha passwords in FinWise.
- Do not commit credentials, cookies, exported private data, screenshots, or raw HTML dumps.
- Store only the fields needed for business judgment and evidence review.
- Keep source provider, scan time, and evidence text for auditability.
- Respect platform access restrictions and rate limits.
- Stop collection when login verification, captcha, or source ambiguity requires user intervention.

## 10. Testing Strategy

Backend tests:

- Create technology profiles and tags.
- Upsert scan results idempotently.
- Preserve provider, evidence, status, and confidence.
- Confirm and reject pending tags.
- Keep data scoped by organization and enterprise.

Frontend tests:

- Enterprise roster displays technology profile status.
- Enterprise detail displays qualification tags and evidence.
- Pending tags expose confirm and reject actions.

Skill tests:

- Parse saved mock snippets from Tianyancha and Qichacha into the normalized schema.
- Handle missing enterprise result, ambiguous result, login required, and provider timeout.
- Resume a partial scan without duplicating tags.

## 11. First Implementation Boundary

The first implementation should include:

- Backend data model and APIs.
- Enterprise roster and detail display.
- Manual import/upsert API for scan results.
- Codex skill design and a first runnable scanner using authenticated browser sessions.
- Manual confirmation flow.

The first implementation should not include:

- Automated unattended backend scraping.
- Loan scoring.
- Complex cross-provider conflict resolution beyond marking conflicts as pending review.
- Paid API integration unless a valid commercial API contract is later provided.
