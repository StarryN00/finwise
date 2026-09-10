# FinWise Ontology Finance System

按照 Palantir Ontology 理念设计的智能财务系统项目。

## 当前阶段

当前为独立绿地实现，不绑定任何既有 FinWise 实现。

## 本地启动

需要 Python 3.9+。项目默认使用本地 SQLite 和 `data/artifacts` 原始资料目录，不需要外部数据库。

```bash
python3 -m pip install -e '.[test]'
python3 -m pytest -q
python3 -m uvicorn app.main:app --reload --port 8766
```

服务地址为 <http://127.0.0.1:8766/>。正式企业总览位于 `/static/portfolio.html`，期间工作台位于 `/static/operator.html`，两者都只读取当前登录人被授权的 Scope；已确认的交互原型位于 `/static/operator-workbench-demo.html`，仍使用独立模拟数据，不应把原型的凭证和进度当作真实账务。

默认开启认证：身份、角色和六段 Scope 授权由服务端管理，不能通过 `X-Actor-Id` / `X-Role` 自行赋权。无默认账号或默认密码。只在隔离的合成测试环境中使用 `FINWISE_REQUIRE_AUTH=false`；不要对真实资料或公网服务关闭认证。

本地显式建立操作人与处理范围授权：

```bash
python3 scripts/manage_access.py create-user accountant --role accountant
python3 scripts/manage_access.py grant-scope accountant --scope-file /absolute/path/scope.json
```

密码通过不回显的终端提示输入，不放在命令行或代码里。`scope.json` 包含 `tenant_id`、`organization_id`、`legal_entity_id`、`ledger_id`、`accounting_period_id`、`baseline_id` 六个精确字段。`disable-user` 可禁用账号并撤销会话。

登录接口 `POST /api/v1/auth/login` 接收 `username/password`，返回 `HttpOnly` 会话 Cookie 和 CSRF 令牌；后续 POST 请求必须携带 `X-CSRF-Token`，`GET /api/v1/auth/me` 可恢复登录上下文，`POST /api/v1/auth/logout` 撤销会话。`/static/operator.html` 提供正式认证后的企业选择、原件接收、解析、基线核对和命令操作界面；原来的单企业页面所写死的角色头不再授予权限。

不要直接双击 `static/index.html` 作为完整应用入口；文件模式现在可以正常显示样式，但演示和查询仍需要后端服务。若直接打开 `static/operator.html`，页面会自动切换到本机 `8767` Staging 服务。未登录时只显示账号密码表单，登录成功后才显示该账号获权的处理范围。

### Staging 真实 Gateway

本地 fixture 测试默认保持 `FINWISE_AGENT_MODE=disabled`。Staging 才启用服务端真实 Gateway；Harness 可加 `--replay` 验证固定输入回放：

```bash
cp deploy/staging.env.example deploy/staging.env
# 仅在本机密钥文件中填写 FINWISE_DEEPSEEK_API_KEY 和 Staging 测试账号
docker compose -f deploy/docker-compose.staging.yml up -d --build
python3 scripts/run_real_agent_harness.py --preflight
```

Staging 使用独立 SQLite 和原始资料卷，必须开启认证；没有 API Key、Scope、业务组或 Harness 账号时应保持阻断。Harness 不接受 `model_output`，会通过登录、CSRF 和 `/api/v1/agent/*` 真实链路执行，并在报告中记录 `mock=false`、模型、Prompt 版本、输入/输出哈希和 Run ID。当前不连接生产数据，也不执行生产部署。

### 易代账文件适配

易代账适配器不会猜测供应商模板字段。先检查实际模板：

```bash
python3 scripts/yidaizhang_adapter.py inspect-template /path/to/yidaizhang-template.xlsx
python3 scripts/yidaizhang_adapter.py export \
  --export-json /path/to/export.json \
  --scope-json /path/to/scope.json \
  --template /path/to/yidaizhang-template.xlsx \
  --profile /path/to/yidaizhang-profile.json \
  --output /path/to/yidaizhang-import.xlsx \
  --manifest /path/to/yidaizhang-manifest.json
python3 scripts/yidaizhang_adapter.py validate-receipt /path/to/receipt.json --manifest /path/to/manifest.json
```

XLSX/CSV 回执必须同时提供明确的 `TemplateProfile` 字段映射；成功、失败和部分成功以外的状态会被拒绝。实际导入模板、回执样例和测试账套准备好后，再执行真实易代账导入回执闭环。

数据库迁移是幂等的，应用启动时自动执行；也可以运行：

```bash
python3 scripts/migrate.py
```

## 目录说明

- `app/ontology/`：对象、关系、版本、规则、对账、命令、Run 和 Gateway。
- `migrations/`：SQLite schema 迁移。
- `static/`：期间工作台与确认卡证据视图。
- `static/portfolio.html`：正式只读企业/账套/期间总览入口；`GET /api/v1/portfolio` 只返回当前身份被授权的范围。
- `static/operator.html`：正式认证工作台，连接原件接收、解析、基线候选、对象详情和受控命令。
- `tests/`：L1 契约/集成测试、采购纵向切片与真实表格解析边界测试。
- `scripts/run_juxianda_ingestion.py`：在临时 Scope 中只读验收聚贤达资料；默认读取共享目录，不修改原件、不调用外部模型。
- `docs/ACCEPTANCE_REPORT.md`：按 T00–T18 的验收映射。

所有正式状态写入必须经过 `POST /api/v1/commands`；兼容入口 `POST /api/v1/business/procurement` 也会转译为 `create_procurement_group` 命令并保留幂等记录。Agent 只允许生成候选建议、规则候选和确认卡。真实模型、部署环境和生产企业验收未在本地实现中冒充通过。

外部回执命令 `ack_external_import` 必须携带真实的 `status`（`IMPORTED` / `FAILED` / `PARTIAL`）、`external_batch`、`export_id`、`voucher_version_id` 和整数 `voucher_version`。后三项必须与该交付包中的导出记录完全一致；失败、部分成功或引用不一致均不能形成整期归档许可。合成测试回执仅证明门禁逻辑，不代表外部软件已经入账。

采购核对按业务组中的**全部**发票、付款计算，逐张检查价税合计和税额；缺失或非法值不能按零处理。同来源哈希、定位和类型的事实重复提交会复用原记录，解析内容发生变化必须明确重新解析。已确认主归属会同时检查专用编号与来源外部编号，不能通过补字段或更换行号重复记账。

`ontology-v1.3` 保留 v1.2 的凭证金额编码：新凭证金额、复核借贷合计使用两位十进制字符串，旧数字金额仍可读取。来源更正后须重新校验；未交付凭证可生成新修订并重新复核，旧版本保留，已进入交付包的版本不可普通修改。测试金额均为合成数据，不代表真实企业交付。

`ontology-v1.3` 同时提供只读、版本化 ActionType 目录。当原件、来源定位、解析与范围门禁均通过，但业务类型仍未识别时，工作台使用 `decision-v2` 提供记录专业判断、暂停、请求补充、标记本期不处理和转交复核五类受控动作。执行与撤销分别经 `execute_task_action` / `revoke_task_action` 命令，均绑定任务指纹、原件版本、幂等键并保留审计；所有结构化效果均不授予账务可用。旧 `decision-v1` 仅兼容只读展示。

### 表格资料解析

当前已接入 `POST /api/v1/commands` 的 `parse_artifact` 命令，支持采购进项、销售发票、合同、入库单、银行流水、工资、社保、公积金、电子承兑、个人所得税申报和期初余额表的真实 `.xls/.xlsx` 原件解析。解析器会保存工作表、行号、单元格区域、原始值、规范值和缺口；跨期记录、非法金额、未知方向和公式值不会被猜测或补零。原件未提供税率时保留空值与原税额，不判为提取错误；非法税率、明示税率与税额差异仍需核对，后续账务门禁不变。解析失败只记录原始资料的失败状态，不生成事实。工资表中的说明行、公司标题和社保拆分行会保留在原件中，但不会被误记为工资事实。

解析选项只能提交 `document_kind` 和可选的本方银行账号标识，客户端不能注入解析结果。`operator`、`accountant`、`admin` 可执行，`viewer` 和 `reviewer` 不可执行。相同原件已解析后再次执行只读复用已有事实，不重写原件或制造重复事实。

### 期初基线确认

当前契约为 `ontology-v1.3`，保留上述金额编码，并收紧 `confirm_baseline`。先在目标 Scope 上传上期余额和结账依据原件，其 `observed_period` 必须是紧邻上月；这些资料保留期间例外状态，不会因此变为本期业务事实。可调用只读 `POST /api/v1/baseline/candidate`，传入 `scope`、`balance_artifact_id` 和 `close_artifact_id`，系统会按科目及辅助项逐行比较期初与上期末金额，并返回来源定位、缺口、四项合计和待确认草稿。确认仍走命令接口，携带目标基线最新版本，`payload` 必须包含：

- `prior_period`、`close_reference`、`currency: "CNY"`、`completeness_confirmed: true`。
- `balance_source`、`close_source`：各含 `artifact_id`、整数 `version`、非空 `anchor`（页码、行号、字段或区域）。
- `balances`：完整的人工核对科目明细，每行含 `account_code`、`account_name`、`source_anchor`、`requires_auxiliary`，以及 `closing_debit`、`closing_credit`、`opening_debit`、`opening_credit` 四个精确金额；金额建议传两位十进制字符串。
- 需要辅助核算的行必须提供 `auxiliary`，每项有唯一 `key`、`source_anchor` 和上述四个金额字段，汇总必须等于科目控制余额。

完整机器可读结构见 `GET /api/v1/ontology/contract` 的 `baseline_confirmation_schema`。每科目期初必须与上期期末一致，试算借贷相等；未知字段、空来源、旧版本、跨范围引用和被修改的原件均拒绝。旧版仅 `opening_balance_verified: true` 的记录不能继续放行，须补齐原件及明细重新确认；历史版本不被覆盖。

生成、复核、交付、首次导出和关账均重新检查基线来源。基线修订后须重新校验业务组并修订未交付凭证。工作台的 `baseline_validation` 表示查询时有效性，与历史对象的 `CONFIRMED` 状态分开；已存在的不可变导出不会因再次下载而改写。

这一步现在支持从两份紧邻上期的余额原件自动提取并逐科目/辅助项比较，但仍是**人工确认前的确定性候选**，不是权威科目表完整性证明，也不会自动建立内部上期关闭快照或完成新企业首次建账。不可用随意上传的文件和人工填数宣称这些能力已经完成，也不可在真实 Scope 使用合成 Demo 基线。

## 核心目标

- 建立稳定、不可变、可追溯的财务事实基础
- 以 BusinessFact、BusinessEvent 和 ProcessingGroup 表达真实业务
- 通过证据、规则、对账和命令门禁控制账务动作
- 让 Agent 负责理解和建议，不直接修改正式账务
- 支持业务规则复用、异常隔离、版本修订和历史回放
- 为税务、资产、资金、报表和外部系统扩展提供稳定底座

## 文档

- [产品设计文档](docs/PRODUCT_DESIGN.md)
- [流程全貌图](docs/flow-overview.mmd)

## 开发边界

第一阶段不开放无人过账、自动锁账或不可追溯的自动修订。

所有后续实现都必须遵守：

```text
事实、证据、判断、规则、结果、动作严格分层
所有对象和任务带完整 Scope
所有写动作经过命令授权和确定性门禁
已交付对象不可原地修改
```
