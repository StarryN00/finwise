# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

**智税管家 (FinWise)** — an enterprise financial/tax service SaaS platform. The company positions itself as an "enterprise full-lifecycle service provider," using AI-driven financial analysis as the core differentiator, with tax filing and financing matchmaking as the business loop.

Target users for Phase 1: internal business operators (业务员). Multi-role support (代账公司, 银行客经理, 企业客户) is architecturally reserved but not built in Phase 1.

## Technology Stack

- **Frontend:** Vue 3 + Element Plus + ECharts
- **Backend:** Python FastAPI
- **Database:** PostgreSQL (single instance, no Redis/Celery in Phase 1)
- **AI:** 国内 AI 模型（Kimi / MiniMax / GLM）— W1 spike 测试后确定主用模型
- **File Storage:** Local disk (Phase 1), Aliyun OSS later
- **Deployment:** Single Aliyun ECS instance

## Architecture

Four-layer architecture (L1-L4):
1. **Presentation** — Vue 3 SPA with Element Plus components, ECharts for data visualization
2. **Business Logic** — FastAPI handling workflow orchestration, rules engine, permissions
3. **AI Processing** — LLM API calls with prompt engineering for parsing, matching, and report generation
4. **Data** — PostgreSQL with structured storage, local file storage

## Phase 1 MVP Scope (Apr 18 - May 31, 2026)

Goal: deliver complete service for at least 2 clients, validating the core loop of data import -> tax filing -> financial analysis -> financing recommendation.

Core modules to build:
1. **Data Import & AI Parsing** — invoice import, bank statement AI parsing, statement-invoice matching
2. **VAT Filing** — VAT + surcharge monthly filing (Jiangsu province only), Excel export in tax bureau format
3. **Financial Health Analysis** — 5-dimension analysis, PDF/HTML report generation, financing need scoring

Financing product matching is simplified: Excel-maintained product library with manual matching by operators.

## Key Design Decisions

- All data models must include `channel_id` (UUID, default value) for future multi-tenant/OEM support
- Report templates must use placeholders for logo, company name, contact info (OEM readiness)
- API queries should have a middleware slot for channel isolation (empty implementation in Phase 1)
- AI API calls must use desensitized data only — never send enterprise names or tax IDs to LLM
- Bank statement parsing must always include a human confirmation step (AI accuracy safeguard)
- Tax rates and filing rules must be configurable (policy changes are expected)
- Monitor per-enterprise API call costs with alerting

## Language

- Code, comments, and API naming: English
- UI text, reports, and business terminology: Chinese (zh-CN)
- Product documentation is in Chinese (see `docs/产品规划.md`)

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health
