# 智税管家 · 第一期 PRD

**版本：** v1.0
**日期：** 2026年4月
**状态：** 开发基准
**范围：** 第一期 MVP（4月18日 - 5月31日）

---

## 1. 功能范围

### 1.1 核心模块

第一期开发以下四个核心模块，验证"导入→申报→分析→融资推荐"核心业务闭环：

| 模块 | 功能 | 说明 |
|------|------|------|
| **企业管理** | 企业 CRUD、客户列表 | 业务员录入和管理客户企业 |
| **数据导入与 AI 解析** | 发票导入、银行流水 AI 解析、流水-发票匹配 | 支持 Excel/CSV/PDF，需人工确认 |
| **增值税申报** | VAT + 附加税月报自动生成 | 仅限江苏省，导出 Excel |
| **财务健康分析** | 五维度分析、PDF/HTML 报告、融资需求评分 | 评分 0-100，高潜力客户标记 |

### 1.2 页面清单

| # | 页面 | 路由 | 功能描述 |
|---|------|------|----------|
| 1 | 登录页 | `/login` | 用户名+密码登录 |
| 2 | 企业总览（首页） | `/` | 仪表盘：企业总数/已分析/高潜力/待处理；企业列表按评分排序 |
| 3 | 企业详情页 | `/enterprise/{id}` | 基本信息 + 融资评分仪表盘 + 五维雷达图 + 历史时间线 |
| 4 | 数据导入页 | `/enterprise/{id}/import` | 步骤条：上传→AI解析→人工确认→完成 |
| 5 | 财务健康报告页 | `/enterprise/{id}/report` | PDF/HTML 报告预览，支持导出 |
| 6 | 新增企业表单 | `/enterprise/new` | 企业信息录入表单 |

### 1.3 用户角色

- **内部业务员**：第一期唯一角色，可操作所有功能
- 渠道方（代账公司/银行客经理）：架构预留，第一期不开发

### 1.4 第一期不开发项

- 税务筹划模块
- 项目申报辅助
- 融资产品匹配（简化版：Excel 维护，手动匹配）
- 财务报表调整
- 贷后风险分析
- 渠道方 OEM

---

## 2. API 接口设计（FastAPI Routes）

### 2.1 认证模块 `/api/auth`

```
POST   /api/auth/login          # 登录，返回 JWT token
POST   /api/auth/logout         # 登出
GET    /api/auth/me             # 获取当前用户信息
```

### 2.2 企业管理 `/api/enterprises`

```
GET    /api/enterprises                    # 企业列表（分页、筛选、排序）
POST   /api/enterprises                    # 新增企业
GET    /api/enterprises/{id}               # 获取企业详情
PUT    /api/enterprises/{id}               # 更新企业信息
DELETE /api/enterprises/{id}               # 删除企业
GET    /api/enterprises/{id}/summary       # 获取企业摘要（统计摘要）
```

### 2.3 数据导入 `/api/enterprises/{id}/import`

```
POST   /api/import/invoices                 # 导入发票（Excel/CSV）
POST   /api/import/bank_statements         # 导入银行流水（Excel/CSV/PDF）
POST   /api/import/financial_statements     # 导入财务报表（Excel）
GET    /api/import/jobs/{job_id}           # 获取导入任务状态
```

### 2.4 AI 解析 `/api/parse`

```
POST   /api/parse/bank_statement           # AI 解析银行流水（返回待确认数据）
POST   /api/parse/bank_statement/confirm  # 确认解析结果
POST   /api/parse/match                   # 流水-发票智能匹配（返回候选）
POST   /api/parse/match/confirm           # 确认匹配结果
```

### 2.5 增值税申报 `/api/tax`

```
POST   /api/tax/vat/calculate             # 计算 VAT 申报数据
GET    /api/tax/vat/{enterprise_id}       # 获取企业 VAT 申报记录
GET    /api/tax/vat/{enterprise_id}/export # 导出 Excel（税务局格式）
```

### 2.6 财务分析 `/api/analysis`

```
POST   /api/analysis/health               # 生成财务健康分析报告
GET    /api/analysis/{enterprise_id}      # 获取企业分析报告列表
GET    /api/analysis/{enterprise_id}/latest # 获取最新报告
GET    /api/analysis/{report_id}          # 获取报告详情
GET    /api/analysis/{report_id}/export   # 导出报告（PDF/HTML）
```

### 2.7 融资评分 `/api/financing`

```
POST   /api/financing/score               # 计算融资需求评分
GET    /api/financing/{enterprise_id}     # 获取企业融资评分历史
```

### 2.8 文件 `/api/files`

```
POST   /api/files/upload                  # 上传文件
GET    /api/files/{file_id}                # 下载文件
DELETE /api/files/{file_id}               # 删除文件
```

---

## 3. JSON 数据模型

### 3.1 核心实体

#### Enterprise（企业）

```json
{
  "id": "uuid",
  "channel_id": "uuid",
  "name": "string",
  "tax_number": "string",
  "taxpayer_type": "GENERAL | SMALL",
  "industry": "string",
  "registered_capital_range": "string",
  "founded_year": "integer",
  "province": "string",
  "city": "string",
  "source": "DIRECT | LIU | PING",
  "assigned_operator_id": "uuid",
  "status": "ACTIVE | INACTIVE",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

#### Invoice（发票）

```json
{
  "id": "uuid",
  "enterprise_id": "uuid",
  "invoice_number": "string",
  "invoice_type": "VAT_SPECIAL | VAT_NORMAL",
  "issue_date": "date",
  "amount": "decimal",
  "tax_amount": "decimal",
  "total_amount": "decimal",
  "seller_name": "string",
  "seller_tax_number": "string",
  "buyer_name": "string",
  "buyer_tax_number": "string",
  "status": "PENDING | MATCHED | ANOMALY",
  "import_batch_id": "uuid",
  "created_at": "datetime"
}
```

#### BankTransaction（银行流水）

```json
{
  "id": "uuid",
  "enterprise_id": "uuid",
  "transaction_date": "date",
  "summary": "string",
  "debit_amount": "decimal",
  "credit_amount": "decimal",
  "balance": "decimal",
  "account_number": "string",
  "confidence": "float",
  "status": "PENDING | CONFIRMED | DELETED",
  "matched_invoice_id": "uuid | null",
  "import_batch_id": "uuid",
  "created_at": "datetime"
}
```

#### FinancialStatement（财务报表）

```json
{
  "id": "uuid",
  "enterprise_id": "uuid",
  "statement_type": "BALANCE_SHEET | INCOME | CASH_FLOW",
  "period_year": "integer",
  "period_month": "integer",
  "data": "json",
  "import_batch_id": "uuid",
  "created_at": "datetime"
}
```

#### VATFiling（增值税申报）

```json
{
  "id": "uuid",
  "enterprise_id": "uuid",
  "period_year": "integer",
  "period_month": "integer",
  "taxpayer_type": "GENERAL | SMALL",
  "sales_amount": "decimal",
  "tax_rate": "decimal",
  "tax_amount": "decimal",
  "surcharge_amount": "decimal",
  "total_tax": "decimal",
  "status": "DRAFT | CONFIRMED | FILED",
  "excel_url": "string",
  "created_at": "datetime"
}
```

#### HealthAnalysisReport（财务健康分析报告）

```json
{
  "id": "uuid",
  "enterprise_id": "uuid",
  "report_number": "string",
  "analysis_date": "date",
  "overall_score": "integer",
  "overall_grade": "A_PLUS | A | B_PLUS | B | C | D",
  "profitability_score": "float",
  "solvency_score": "float",
  "operation_efficiency_score": "float",
  "growth_score": "float",
  "cash_flow_score": "float",
  "radar_data": {
    "profitability": "float",
    "solvency": "float",
    "operation_efficiency": "float",
    "growth": "float",
    "cash_flow": "float"
  },
  "key_metrics": "json",
  "ai_interpretation": "string",
  "risk_alerts": ["string"],
  "improvement_suggestions": ["string"],
  "financing_score": "integer",
  "estimated_loan_amount": "decimal",
  "matched_products": ["string"],
  "pdf_url": "string",
  "html_url": "string",
  "status": "GENERATING | COMPLETED | FAILED",
  "created_at": "datetime"
}
```

#### User（用户/业务员）

```json
{
  "id": "uuid",
  "username": "string",
  "password_hash": "string",
  "real_name": "string",
  "role": "OPERATOR | ADMIN",
  "status": "ACTIVE | INACTIVE",
  "created_at": "datetime"
}
```

#### ImportBatch（导入批次）

```json
{
  "id": "uuid",
  "enterprise_id": "uuid",
  "import_type": "INVOICE | BANK_STATEMENT | FINANCIAL_STATEMENT",
  "file_name": "string",
  "total_rows": "integer",
  "processed_rows": "integer",
  "status": "PENDING | PROCESSING | COMPLETED | FAILED",
  "error_message": "string | null",
  "created_at": "datetime"
}
```

### 3.2 请求/响应模型

#### LoginRequest

```json
{
  "username": "string",
  "password": "string"
}
```

#### LoginResponse

```json
{
  "access_token": "string",
  "token_type": "bearer",
  "expires_in": "integer",
  "user": {
    "id": "uuid",
    "username": "string",
    "real_name": "string",
    "role": "string"
  }
}
```

#### EnterpriseListResponse

```json
{
  "total": "integer",
  "page": "integer",
  "page_size": "integer",
  "items": [{
    "id": "uuid",
    "name": "string",
    "industry": "string",
    "financing_score": "integer",
    "last_analysis_date": "date | null",
    "status": "string",
    "source": "string"
  }]
}
```

#### BankStatementParseRequest

```json
{
  "enterprise_id": "uuid",
  "file_id": "uuid"
}
```

#### BankStatementParseResponse

```json
{
  "job_id": "uuid",
  "status": "PROCESSING"
}
```

#### BankStatementConfirmRequest

```json
{
  "enterprise_id": "uuid",
  "transactions": [{
    "row_index": "integer",
    "transaction_date": "date",
    "summary": "string",
    "debit_amount": "decimal",
    "credit_amount": "decimal",
    "balance": "decimal",
    "status": "CONFIRMED | DELETED"
  }]
}
```

#### VATCalculateRequest

```json
{
  "enterprise_id": "uuid",
  "period_year": "integer",
  "period_month": "integer"
}
```

#### VATCalculateResponse

```json
{
  "filing_id": "uuid",
  "sales_amount": "decimal",
  "tax_rate": "decimal",
  "tax_amount": "decimal",
  "surcharge_amount": "decimal",
  "total_tax": "decimal",
  "details": [{
    "item": "string",
    "amount": "decimal"
  }]
}
```

#### HealthAnalysisRequest

```json
{
  "enterprise_id": "uuid",
  "report_type": "FULL | QUICK"
}
```

#### HealthAnalysisResponse

```json
{
  "report_id": "uuid",
  "status": "GENERATING"
}
```

#### FinancingScoreResponse

```json
{
  "enterprise_id": "uuid",
  "score": "integer",
  "level": "HIGH | MEDIUM | LOW",
  "estimated_loan_amount": "decimal",
  "matched_products": [{
    "product_name": "string",
    "max_amount": "decimal",
    "interest_rate_range": "string",
    "basic_requirements": ["string"]
  }],
  "scoring_factors": [{
    "factor": "string",
    "weight": "float",
    "score": "integer"
  }]
}
```

### 3.3 错误响应模型

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "details": "object | null"
  }
}
```

常用错误码：

| code | 说明 |
|------|------|
| `AUTH_INVALID_CREDENTIALS` | 用户名或密码错误 |
| `AUTH_TOKEN_EXPIRED` | Token 已过期 |
| `ENTERPRISE_NOT_FOUND` | 企业不存在 |
| `IMPORT_JOB_NOT_FOUND` | 导入任务不存在 |
| `ANALYSIS_IN_PROGRESS` | 分析任务进行中 |
| `FILE_TYPE_NOT_SUPPORTED` | 文件类型不支持 |
| `VALIDATION_ERROR` | 参数校验失败 |

---

## 4. 数据库表设计（PostgreSQL）

### 4.1 表清单

| 表名 | 说明 |
|------|------|
| `users` | 用户表 |
| `enterprises` | 企业表 |
| `invoices` | 发票表 |
| `bank_transactions` | 银行流水表 |
| `financial_statements` | 财务报表表 |
| `vat_filings` | VAT 申报表 |
| `health_reports` | 健康分析报告表 |
| `import_batches` | 导入批次表 |
| `ai_parse_logs` | AI 解析日志表 |
| `operation_logs` | 操作日志表 |

### 4.2 关键索引

- `enterprises`: `idx_enterprises_channel_id`, `idx_enterprises_source`
- `invoices`: `idx_invoices_enterprise_id`, `idx_invoices_issue_date`
- `bank_transactions`: `idx_bank_tx_enterprise_id`, `idx_bank_tx_date`, `idx_bank_tx_matched_invoice`
- `health_reports`: `idx_health_reports_enterprise_id`, `idx_health_reports_date`

---

## 5. AI 能力使用规范

### 5.1 场景与模型选择

| 场景 | 模型 | 原因 |
|------|------|------|
| 银行流水解析 | Claude Haiku | 成本最低，结构化任务 |
| 流水-发票匹配 | Claude Haiku | 候选推荐，规则明确 |
| 财务健康分析 | Claude Sonnet | 保质量，复杂解读 |

### 5.2 数据安全要求

- **严禁**将企业名称、统一社会信用代码传输给 LLM
- AI API 调用前必须进行数据脱敏处理
- 银行流水解析结果必须经人工确认后才能入库

---

## 6. 第一期 W1-W6 开发计划

| 周次 | 任务 | 交付物 |
|------|------|--------|
| W1 | 项目骨架 + 企业管理 + 登录 | 可登录系统，可新增/查询企业 |
| W2 | 发票导入 + 银行流水 AI 解析 | 两类数据可导入并解析 |
| W3 | 流水-发票匹配 + 财报导入 | 三类数据打通 |
| W4 | 增值税申报计算 + Excel 输出 | 可导出税务格式文件 |
| W5 | 财务健康分析 + 报告生成 | PDF/HTML 报告 + 融资评分 |
| W6 | 联调测试 + 第一个客户交付 | 完整交付 |

---

## 7. 技术约束

- 数据库：PostgreSQL（单机）
- 文件存储：本地磁盘（`/data/files/`）
- AI：国内模型（MimiMax/GLM/Kimi 待定）
- 部署：阿里云单台 ECS
- 无 Redis、无 Celery（第一期）

---

_智税管家 · 第一期 PRD · 2026年4月_
