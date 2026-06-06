# 智税管家（FinWise Accounting）整体架构评审与优化建议

> 评审日期：2026-06-01
> 评审范围：`finwise-accounting/` 下的 backend（FastAPI）与 frontend（Vue 3）全量代码
> 评审方式：分段通读 —— 架构骨架 → 后端服务层 → 后端 API 层 → 前端视图层 → 汇总
> 代码规模：后端 ~10.5K 行 Python（50+ 文件），前端 ~7K 行 Vue（25 视图/组件）

本文档面向工程负责人，目标是：（1）还原系统的整体流程与模块边界；（2）逐模块给出代码与交互层面的优化建议；（3）给出一份分优先级的改进清单。**本文档只做评审与建议，不含代码改动。**

---

## 一、系统全景

### 1.1 技术栈实况

| 层 | 技术 | 备注 |
|---|---|---|
| 前端 | Vue 3 + Element Plus + ECharts + Pinia + axios | Vite，端口 5174 |
| 后端 | FastAPI + SQLAlchemy 2.0 ORM | 默认 SQLite，PG 经 `postgresql+psycopg` 归一化 |
| AI | `openai` SDK（依赖已装）+ 实际用裸 `urllib` 调 Moonshot/Kimi | `enable_ai` 默认关；超时 45s/180s |
| 报告 PDF | 独立子系统 `backend/finreport/`（analyzer / kimi_writer / chart_maker / pdf_renderer） | matplotlib 出图 |
| 存储 | 本地磁盘 `storage/uploads/`（tax_exports / reports / charts） | 符合 Phase1 约定 |

### 1.2 请求链路

```
Vue View
  → api/client.js（axios，统一 /api 前缀，唯一 API 契约出口）
    → FastAPI Router（app/api/*.py）
      → Service（app/services/*.py，业务逻辑全部在此）
        → SQLAlchemy ORM（app/models/entities.py）
          → SQLite / PostgreSQL
```

`frontend/src/api/client.js` 把所有 50 个端点集中成一个 `api` 对象，是很好的设计——前后端契约只有这一个出口，改接口时只需改一处。

### 1.3 核心业务闭环（Phase 1 主线）

```
① 企业建档 + 科目初始化 + 期初快照
        │
        ▼
② 创建月度工作包（MonthlyWorkPackage = 整个系统的中枢实体）
        │
        ▼
③ 导入资料（银行流水 / 进项明细 / 销项明细）── import_service
        │
        ▼
④ 自动匹配（金额相等+7天内，双向唯一）── matching_service
   ＋ AI 匹配（可选，脱敏后送 LLM，超时本地兜底）── ai_matching_service
        │
        ▼
⑤ 人工确认（匹配 / 账目行 / 未匹配源，可沉淀为企业规则）
        │
        ├──────────────┬───────────────┐
        ▼              ▼               ▼
⑥ 凭证生成        ⑦ 月度报表       ⑧ 增值税申报草稿
  voucher_service   statement_service  tax_service
  （借贷分录）       （资产负债+利润表估算）（销项-进项→应纳税额）
        │                              │
        ▼                              ▼
⑨ 财务健康报告（report_service → finreport PDF，8 段诊断）
```

### 1.4 数据模型（26 张表）

中枢是 `MonthlyWorkPackage`，挂载所有月度数据：
`BankTransaction / Invoice`（源）→ `MatchRecord`（匹配）→ `AccountingLine`（账目行）→ `Voucher / VoucherEntry`（凭证）→ `MonthlyStatement / TaxFilingDraft / Report`（输出）。

旁支模块：
- **技术画像**（`TechnologyProfile / TechnologyTag / TechnologyScanJob / TechnologyScanJobItem`）—— 与 Phase 1 记账主线无关的独立大模块。
- **历史导入**（`HistoricalImportBatch / HistoricalLedgerEntry / HistoricalBalanceRow`）—— GB/T24589 标准账套导入。
- **两套规则**：`MatchingRule`（账目匹配级，摘要→业务类型）与 `VoucherRule`（凭证分录级，业务→借贷科目）—— **职责不同，不是冗余**（评审中一度误判，已更正）。

所有表均带 `channel_id`，符合 CLAUDE.md 的多租户/OEM 预留约定。

---

## 二、逐模块评审

### 模块 A：导入与解析（import_service.py，400 行）

**职责**：银行流水、进销项发票的 Excel/CSV 解析入库。

**亮点**
- `BANK_COLUMNS` / `INVOICE_COLUMNS` 列别名映射覆盖了大量真实银行/税局模板（含带英文括号的字段名），`pick()` 还做归一化模糊匹配。
- 单边金额列的方向推断（借贷标志 → 付款人/收款人主体匹配 → 金额正负）逐级兜底，工程上很务实。
- 汇总行过滤、`_json_safe_row` 序列化、逐行错误收集且不阻断整批。

**建议**
- 🟡 `to_date` 函数 50 行手写日期解析，分支密集。可考虑用 `pandas.to_datetime(errors='coerce')` 兜底，保留现有规则作为快路径。
- 🟡 列别名表越来越长，建议迁到配置（JSON/YAML），让运营能在不改代码的情况下补充模板别名 —— 与 CLAUDE.md "导入规则可配置" 的精神一致。
- 🟢 银行 PDF 解析仍未实现（Phase1 audit 已记录），目前只支持结构化表格。

### 模块 B：匹配引擎（matching_service.py 713 行 + ai_matching_service.py 488 行）

**职责**：自动对账（流水↔发票）、规则记忆、人工确认流转。

**亮点**
- 自动匹配采用**双向唯一性校验**（一笔流水只对一张发票、反之亦然），避免一对多误匹配。
- **幂等设计**：用 `existing_pairs` / `existing_line_keys` + 数据库唯一约束，重复运行匹配不会产生重复记录。
- 内置规则优先于企业记忆规则（注释明确："policy-maintained classifications take precedence"），符合"政策规则 > 个人习惯"的业务直觉。
- AI 匹配的**隐私保护到位**：主体名替换为 `SELF`/`P001` 别名、摘要脱敏、金额日期方向化，完全符合 CLAUDE.md "AI 只收脱敏数据" 的硬约束。超时还有本地候选兜底（`AI_FALLBACK_RULE` / `AI_FALLBACK_CANDIDATE`），不会因 AI 不可用卡死流程。

**建议**
- 🟠 `_get_monthly_package`（带 org 校验）在 import / matching / statement / tax / report / voucher 各 service 里**各写了一份**，6 处重复。建议下沉为一个公共依赖（如 `app/services/common.py` 或 FastAPI 依赖），统一企业隔离校验。
- 🟡 AI 调用用裸 `urllib.request` 手写超时/错误处理，而项目已依赖 `openai` SDK。统一改用 SDK 可获得重试、流式、统一异常等能力，并减少手写 HTTP 代码。
- 🟡 `_extract_summary_keyword` 的中文前后缀裁剪是启发式硬编码（"支付/缴纳/服务费/手续费"…），可维护性一般；可考虑配置化或记录裁剪效果以便调参。

### 模块 C：凭证工作台（voucher_service.py，**2357 行**）

**职责**：凭证草稿生成、确认/驳回/重开、重新匹配、单源处理调整、台账汇总、AI 预处理建议。

**现状**：这是整个系统**最复杂、最重**的模块，单文件 2357 行、60+ 函数，覆盖 7 类凭证生成场景（确认匹配 / 一票多笔 / 一笔多票 / 银行手续费 / 未匹配发票 / 未匹配流水 / 单源刷新）。

**建议**
- 🟠 **强烈建议拆分**。按职责切成多个文件，例如：
  - `voucher_generation.py`（7 类 `_generate_*` + `_build_voucher` + 分录构造）
  - `voucher_lifecycle.py`（confirm / reject / reopen 流转 + 审计）
  - `voucher_rematch.py`（重匹配候选与执行）
  - `voucher_ledger.py`（bank/invoice 台账、summary 组装）
  - `voucher_rules.py`（VoucherRule 记忆）

  当前所有逻辑挤在一个文件，任何改动的回归面都很大。
- 🟡 `_source_data_for_*` / `_*_lines` 系列函数高度同构（output/input × 单笔/合并/差异），存在可参数化合并的空间。
- 🟢 187 个后端测试覆盖了凭证生命周期，拆分时有测试护航，风险可控。

### 模块 D：报表与税务（statement_service.py 179 + tax_service.py 237）

**职责**：基于已确认数据估算资产负债/利润表；汇总进销项算增值税应纳税额；导出 Excel / HTML。

**亮点**
- 增值税计算口径清晰（`vat_payable = max(0, 销项税额 - 进项税额)`，附加税按 12% 估算），未匹配发票数作为告警随草稿带出。
- 草稿支持人工改数后重算（`update_tax_filing_draft`），符合 CLAUDE.md "人工确认环节" 的要求。

**建议**
- 🟠 税务 HTML 模板**内联在 Python 字符串里**（`render_tax_filing_draft_html`），与健康报告同样的问题（见模块 E）。
- 🟡 附加税 12% 系数硬编码，建议与税率一起进配置（CLAUDE.md 要求"税率和申报规则可配置，政策变动可预期"）。

### 模块 E：健康报告（report_service.py 775 + finreport/ 子系统）

**职责**：8 段财务健康诊断报告，AI 写分析 + 系统出图表，产出 HTML + PDF。

**亮点**
- 双通道生成：AI 章节 + 内置兜底文案（`_section_paragraphs` 的 fallback），AI 不可用时报告仍可生成。
- 脱敏严格：`desensitize_ai_payload` / `_mask_company_name` / `_sanitize_summary` 多重清洗，且有 `test_reports_and_privacy.py` 守护。

**建议（含两个需要业务决策的点）**
- 🔴 **伪造对比基期数据**。`_build_finhealth_input` 里用 `previous_balance = {k: v*0.92}`、`previous_income ×0.94`、`previous_vat ×0.96` 凭空生成"上年同期"数据喂给报告。这是给企业老板看的诊断报告，用系数编造的同比基数会产生误导性结论，存在**信任与合规风险**。建议：要么明确标注"同比为系统估算占位、非真实数据"，要么在缺真实历史数据时**不展示同比维度**。
- 🟠 **HTML 模板硬编码在 Python 里**（600+ 行内联 CSS+HTML）。这与 CLAUDE.md "报告模板必须用 logo、公司名、联系方式占位符（OEM readiness）" 的关键设计约定**直接冲突**。当前 OEM 换标只能改 Python 源码。建议抽成 Jinja2 模板（项目已依赖 jinja2）+ 占位符配置。
- 🟡 报告章节标题、风险阈值（资产负债率 0.7、利润率 0.08 等）散落在代码里，建议集中到配置便于行业调参。

### 模块 F：API 层（app/api/，~50 端点）

**亮点**：RESTful 规整，`response_model` 齐全，路由按域聚合。

**建议**
- 🟡 部分 router 用 `prefix`，部分在装饰器里写全路径 `/api/...`（如 matching/tax/vouchers），风格不统一。建议统一用 `APIRouter(prefix=...)`。
- 🟡 企业隔离目前是"软约定"：`get_current_organization_id()` 永远返回默认 org，靠每个 service 自觉带 `organization_id` 过滤，**没有中间件层强制**。CLAUDE.md 提到"API 查询应有 channel 隔离中间件槽位（Phase1 空实现）"——目前连空槽位都未见，多租户上线前必须补。

### 模块 G：前端视图层

#### G1 全局结构
- `AppLayout.vue` 固定侧边栏（8 项导航）+ 顶栏 + slot 内容区，`PackageContextBar`（企业/期间/状态三联选择器）在 6 个月度页面复用，`DataTableShell` 在 5 个列表页复用 —— 组件复用意识好。
- 设计令牌（`tokens.css`）集中管理颜色/圆角/字体，规范。

**建议**
- 🟠 **路由与导航不一致**：`router/index.js` 注册了 14 条路由，但侧边栏只暴露 8 条。`bank-ledger` / `invoice-ledger` / `historical-import` / `enterprise-init` 是"隐藏路由"，用户只能靠按钮跳转或手敲 URL 到达。建议梳理：要么纳入导航（可用分组/二级菜单），要么明确其为"详情子页"并从主导航心智中剥离。

#### G2 账目明细（AccountDetailsView.vue，545 行）
- 交互完整：分段筛选、规则匹配/AI 匹配双按钮、确认弹窗、内联规则配置弹窗。
- AI 匹配有**假进度条**（`startAiProgress` 定时器递增到 96%），缓解长等待焦虑——体验上是加分项。

**建议**
- 🟡 表格 `min-width: 1280px` + 自定义横向滚动条 + range 滑块。13 列信息密度很高，窄屏体验靠手动拖滑块。可考虑列分组/列显隐配置，或把低频列（税额、置信度）收进展开行。
- 🟡 `defaultBusinessType` / `suggestInvoiceDirection` 等业务推断逻辑写在视图里，与后端的业务类型体系是两套；建议下沉或对齐，避免前后端各判一次。

#### G3 凭证工作台（VoucherWorkbenchView.vue，**2185 行**）
- 前端最大的单文件，137 个函数/计算属性，含凭证详情、分录表、重匹配双面板抽屉、处理调整等。

**建议**
- 🟠 **强烈建议拆分**，与后端 voucher_service 对称。可抽出 `VoucherDetailPanel`、`VoucherRematchDrawer`、`SourceCard` 等子组件 + 一个 `useVoucher` composable 管状态。2185 行单组件的可维护性已到临界。

#### G4 输出中心（OutputCenterView.vue）—— 已于本轮优化
- 已统一为三行布局、标题精简、最后一步就地给出查看/下载入口（详见 git 历史）。

### 模块 H：状态管理（stores/workspace.js，97 行）
- 单一 Pinia store，`loadWorkspace` 拉一个聚合快照（`/api/workspace`），所有页面共享。
- `activePackage` getter 兜底逻辑清晰。

**建议**
- 🟡 整个前端只有一个 store，所有状态都塞在 workspace 里。随着技术画像、历史导入等模块增长，建议按域拆分 store（enterprise / voucher / workspace）。

---

## 三、跨模块发现的问题清单（按优先级）

### 🔴 高优先级（上线/合规阻断级）

| # | 问题 | 位置 | 建议 |
|---|---|---|---|
| H1 | `.env` 提交了**真实 Moonshot API key + 企查查账号明文密码** | `.env` | 立即轮换密钥、从版本库移除、加入 `.gitignore`、改用密钥管理；`config.py` 的 `env_file` 还会向上级目录查找，需收敛 |
| H2 | 健康报告**用 0.92/0.94/0.96 系数伪造"上年同期"数据** | `report_service.py` `_build_finhealth_input` | 明确标注为估算占位，或无真实历史时不展示同比 |
| H3 | 报告/税务 **HTML 模板硬编码在 Python**，违反 CLAUDE.md OEM 占位符约定 | `report_service.py`、`tax_service.py` | 抽成 Jinja2 模板 + logo/公司名/联系方式占位符配置 |

### 🟠 中优先级（架构债 / 体验）

| # | 问题 | 位置 | 建议 |
|---|---|---|---|
| M1 | `voucher_service.py` 2357 行、`VoucherWorkbenchView.vue` 2185 行 巨型文件 | — | 按职责拆分（见模块 C / G3），有测试护航 |
| M2 | `_get_monthly_package` 带 org 校验在 6 个 service 重复 | 多处 | 下沉为公共依赖 |
| M3 | 无数据库迁移工具，靠 `main.py` 手写 SQLite `ALTER TABLE` 补丁 | `main.py` | 引入 Alembic；现状下 PG 不执行这些补丁 |
| M4 | 多租户隔离是软约定，无强制中间件 | `org_context.py` / API 层 | 多租户上线前补 channel 隔离中间件 |
| M5 | 前端路由 14 条 vs 导航 8 条，4 条隐藏路由 | `router/index.js` / `AppLayout.vue` | 梳理导航信息架构 |
| M6 | API 路由前缀风格不统一（prefix vs 全路径） | `app/api/*.py` | 统一 `APIRouter(prefix=...)` |
| M7 | 税率/附加税系数/风险阈值硬编码 | tax / report | 按 CLAUDE.md 要求配置化 |

### 🟡 低优先级（规范 / 长期）

| # | 问题 | 建议 |
|---|---|---|
| L1 | `datetime.utcnow()` 全表使用（Py3.12 已弃用，测试 2621 条 warning） | 改 `datetime.now(datetime.UTC)` |
| L2 | AI 调用用裸 `urllib` 而非已装的 `openai` SDK | 统一用 SDK |
| L3 | 单一 Pinia store 承载所有状态 | 按域拆分 store |
| L4 | 成本监控（CLAUDE.md 要求"监控每企业 API 成本并告警"）未实现 | 补埋点 |
| L5 | 审计日志只在 matching 写入，voucher/tax/report 等关键操作未统一落审计 | 统一审计切面 |
| L6 | 列别名表、业务推断逻辑前后端各一套 | 对齐/配置化 |

---

## 四、环境与验证备注

- **后端测试必须用 Python 3.11+**（项目 `requires-python>=3.11`）。系统默认 `python3` 是 3.9.6，会因 3.10+ 联合类型语法（`X | Y`）在收集阶段报 15 个 import 错误。
  正确做法：用 `backend/.venv/bin/python`（3.12.13）。
  ```bash
  cd backend && .venv/bin/python -m pytest -q   # → 187 passed
  ```
- 前端测试：`cd frontend && npm test` → 26 passed（13 文件）。
- README 中的 `cd backend && python3 -m pytest` 在当前机器上会失败，建议更新 README 注明使用 venv。

---

## 五、总体评价

这是一个**完成度相当高、工程务实**的 Phase 1 MVP：核心闭环（导入→匹配→确认→凭证/报表/申报→健康报告）已全程打通，隐私脱敏、幂等匹配、AI 超时兜底、测试覆盖（前端 26 + 后端 187）都达到了可用水准。

主要技术债集中在三点：**（1）两个巨型文件**（voucher 前后端各 2K+ 行）需要拆分；**（2）报告/税务模板硬编码**违反了自己定下的 OEM 占位符约定；**（3）密钥泄露与同比数据伪造**是上线前必须处理的合规项。

建议处理顺序：先清 🔴（密钥轮换 → 同比数据标注 → 模板占位符化），再在有测试护航的前提下推进 🟠 的文件拆分与企业隔离收敛。
