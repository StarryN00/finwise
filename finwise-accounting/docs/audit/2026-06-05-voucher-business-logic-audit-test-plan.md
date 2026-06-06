# 凭证整理业务逻辑专项审核与测试计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:systematic-debugging when a defect is found, and use superpowers:verification-before-completion before claiming any phase is complete.

**目标：** 对核心凭证整理功能做一次可分段执行的业务逻辑审核，重点发现凭证生成、金额分录、来源占用、状态流转、重配/合并、前端操作链路中的逻辑和计算问题。

**范围：** 以 `finwise-accounting` 子项目为准，覆盖后端 `voucher_service.py`、`vouchers.py`、`voucher_ai_preprocess_service.py`、`voucher.py` schema、现有 `test_voucher_service.py` / `test_voucher_api.py`，以及前端 `VoucherWorkbenchView.vue` / `VoucherManagementView.vue` / `client.js` / 对应 spec。

**执行方式：** 每段 45-90 分钟，可独立执行并记录发现。每段结束必须留下：测试命令、通过/失败结果、失败样本、业务影响判断、是否需要修复。

---

## 1. 审核总原则

### 必须持续成立的业务不变量

- 每张可确认凭证必须借贷平衡，金额按 `Decimal` 两位处理，不允许浮点误差进入分录。
- 凭证日期必须落在月度工作包期间内。
- 凭证分录只能使用当前组织、当前企业、启用、末级、允许制凭证的科目。
- 同一个银行流水或发票来源不能同时被多个非驳回凭证占用，除非该凭证是明确的组合来源并在 `source_data` 中保留完整来源数组。
- `generate_voucher_drafts()` 必须幂等：同一工作包重复生成不应重复创建同一来源凭证。
- `REJECTED` 来源不能阻塞重新生成或重配；`CONFIRMED` 来源不能被静默覆盖。
- `voucher_number` 只能在确认时生成；驳回、重开、重配后的草稿不应保留旧编号。
- AI 预处理只产生结构化建议和匹配记录，不应跳过人工确认直接生成已确认凭证。
- 管理页只展示已确认凭证；生成工作台展示待确认、异常、驳回等整理任务。
- UI 不得直接展示后端原始 enum；状态、方向、业务类型必须映射为中文。

### 缺陷分级

- P0：会造成错误记账、借贷不平、重复入账、跨企业/跨期间串数据、确认后凭证被覆盖。
- P1：会造成凭证分录科目错误、差额方向错误、来源状态错误、重配/合并后来源丢失。
- P2：会造成前端误导操作员、中文标签错误、筛选/分页/详情状态与后端不一致。
- P3：体验或可追溯性问题，例如错误提示不清晰、审计信息不足。

---

## 2. 场景覆盖矩阵

| 编号 | 场景 | 关键断言 | 主要测试文件 |
| --- | --- | --- | --- |
| V01 | 销项发票 + 收款 1:1 完全匹配 | 借 `1002`，贷 `5001` + `22210102`；`source_group_type=FULL_MATCH` | `test_voucher_service.py`, `test_voucher_api.py` |
| V02 | 进项发票 + 付款 1:1 完全匹配 | 借费用/成本 + `22210101`，贷 `1002`；税额为 0 时不生成 0 金额行 | 同上 |
| V03 | 销项差额补齐：发票大于收款 | 差额借 `1122`，`difference_amount` 为正，借贷平衡 | 同上 |
| V04 | 销项差额补齐：收款大于发票 | 差额贷 `2203`，`difference_amount` 为负或按设计一致表达 | 同上 |
| V05 | 进项差额补齐：发票大于付款 | 差额贷 `2202`，借贷平衡 | 同上 |
| V06 | 进项差额补齐：付款大于发票 | 差额借 `1123`，借贷平衡 | 同上 |
| V07 | 一张发票多笔流水 | `bank_transaction_ids` 完整，来源不丢失，不再生成单边凭证 | 同上 |
| V08 | 一笔流水多张发票 | `invoice_ids` 完整，合计税额/不含税额正确汇总 | 同上 |
| V09 | 单边销项发票 | 借 `1122`，贷 `5001` + `22210102`；待确认 | 同上 |
| V10 | 单边进项发票 | 借费用/税额，贷 `2202`；待确认 | 同上 |
| V11 | 单边银行收款 | 默认借 `1002`，贷 `2203`；可人工调整 | 同上 |
| V12 | 单边银行付款 | 默认借 `1123`，贷 `1002`；可人工调整 | 同上 |
| V13 | 银行手续费 | 产品标签使用 `银行收费`，分录借手续费类科目、贷银行，不强制对方主体 | 同上 + 前端管理页 spec |
| V14 | 双向往来未开票 | 同一对方收付双向：收款贷 `2241`，付款借 `1221`，`source_group_type=BIDIRECTIONAL_CURRENT_ACCOUNT` | 同上 |
| V15 | 人工处理方式调整 | 只允许单边来源；替换分录、记录 `accounting_treatment`、写入规则 | `test_voucher_api.py` |
| V16 | 重配 1:1 | 替换来源、重建分录、状态回待确认、编号清空、旧来源释放 | `test_voucher_api.py` |
| V17 | 重配 1:N / N:1 | 多选来源数组正确，候选占用状态正确置灰 | `test_voucher_api.py`, `VoucherWorkbenchView.spec.js` |
| V18 | AI 合并建议 | 只合并待确认未编号银行单边凭证；原凭证驳回并标记 `MERGED_BY_OPERATOR` | 同上 |
| V19 | 驳回/重开 | 驳回标记 `OPERATOR_REJECTED`，匹配记录退休；重开清理错误并可再确认 | `test_voucher_service.py`, `test_voucher_api.py` |
| V20 | 已确认管理列表 | API 使用 `status=CONFIRMED`；前端默认 20 条分页，凭证号可打开详情 | `VoucherManagementView.spec.js` + 浏览器 |

---

## 3. 分段执行计划

### Phase 0：基线盘点与样本锁定

**测试目标：** 建立当前覆盖基线，确认本轮审核使用的企业、期间、样本数据和命令，不把环境问题误判为业务问题。

**执行内容：**

- 记录当前分支、未提交改动、Python/Node 依赖状态。
- 跑已有凭证相关后端测试，得到初始失败清单。
- 跑已有凭证相关前端测试，得到初始失败清单。
- 锁定至少一个真实样本工作包，例如黛珂特 2026-04 或当前本地数据库中凭证数最多的工作包。

**建议命令：**

```bash
cd /Users/starryn/project/finwise
git status --short

cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest tests/test_voucher_service.py tests/test_voucher_api.py -q

cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm test -- src/views/VoucherWorkbenchView.spec.js src/views/VoucherManagementView.spec.js src/api/client.spec.js
```

**完成标准：** 形成 `baseline` 记录：通过数、失败数、失败原因、是否属于本轮审核范围。

### Phase 1：凭证生成分支与金额计算审核

**测试目标：** 证明 V01-V14 每个来源分支都能生成正确分录，尤其是差额方向、税额行、组合汇总和双向往来。

**重点检查：**

- `invoice_direction=OUTPUT` 与 `INPUT` 的借贷方向是否完全相反且合理。
- 银行流水方向使用 `debit_amount` / `credit_amount` 时，是否存在收入支出反判。
- 差额为正、负、0 的 `difference_amount` 表达是否一致。
- 多张发票合并时税额、不含税额、价税合计是否分别汇总，而不是用总额反推。
- `source_key` 是否稳定，是否会因来源顺序不同创建重复凭证。
- 双向往来识别是否排除手续费、税费、社保、公积金、工资、利息、平台扣费等特殊主体或摘要。

**需补充或复核的测试：**

- 销项收款大于发票金额时，差额应进入 `2203`，且借贷平衡。
- 进项付款大于发票金额时，差额应进入 `1123`，且借贷平衡。
- 一笔流水多张发票中同时存在两张零税额/非零税额发票时，不生成 0 金额行。
- 同一对方双向往来中，一笔收款、一笔付款分别生成 `2241` / `1221`，不进入普通预收/预付。

**完成标准：** 每个矩阵场景至少有一个后端断言覆盖；所有新发现都能定位到具体分录行或 `source_data` 字段。

### Phase 2：来源占用、幂等、跨期间/跨包隔离

**测试目标：** 找出重复入账、串包、串企业、串组织、重跑覆盖等高风险问题。

**重点检查：**

- 同一工作包重复调用生成接口，`created_vouchers` 第二次应为 0，已有待确认凭证不会被意外重建。
- `REJECTED` 凭证的来源可重新参与新凭证；`CONFIRMED` 凭证的来源不可被重配或合并静默占用。
- 另一个月度工作包中相同发票号、相同银行流水金额，不应影响当前包生成。
- 同一来源被 AI 重新分组后，旧单边凭证应正确标记 `SOURCE_REASSIGNED_BY_AI` 或恢复，不能两个非驳回凭证同时占用。

**建议增加的断言：**

- 查询所有非 `REJECTED` 凭证的 `bank_transaction_ids` / `invoice_ids`，同一来源 ID 出现次数不得超过 1。
- 对同一组 N:1 / 1:N 来源，以不同顺序调用重配，最终 `source_key` 一致。
- 已确认凭证重开后重新确认，编号规则是否符合预期：不重复、不跳回已占用编号。

**完成标准：** 能用一组自动化测试证明来源占用唯一性和幂等性；任何异常都按 P0/P1 记录。

### Phase 3：状态流转、编号、审计记录

**测试目标：** 验证确认、驳回、重开、调整处理方式、合并、重配这些动作不会破坏状态机。

**状态路径：**

```text
PENDING_CONFIRMATION -> CONFIRMED
PENDING_CONFIRMATION -> REJECTED
CONFIRMED -> PENDING_CONFIRMATION
REJECTED -> PENDING_CONFIRMATION
PENDING_CONFIRMATION -> REJECTED(MERGED_BY_OPERATOR) + new PENDING_CONFIRMATION merge voucher
```

**重点检查：**

- 确认失败时必须返回 400，凭证保持待确认，`confirmed_by` / `confirmed_at` / `voucher_number` 不应写入。
- 确认成功时 `voucher_number` 连续，`confirmed_by` / `confirmed_at` 写入。
- 驳回匹配凭证时，对应 `MatchRecord` 变为 `REJECTED`，来源台账变回未匹配/待处理。
- 重开已确认凭证时编号清空还是保留应与产品约定一致；当前重点是不能造成两个确认凭证同号。
- 人工处理方式调整和 AI 合并必须写入审计或可追溯 `source_data`。

**完成标准：** 每条状态路径都有 API 级测试或服务级测试；确认失败无部分写入。

### Phase 4：AI 预处理与隐私/失败路径

**测试目标：** 验证 AI 只作为建议层，不制造不可解释或不可回滚的凭证结果。

**重点检查：**

- 输入给 AI 的 payload 不包含企业名称、税号、原始摘要关键词等敏感字段。
- Kimi 失败、缺 API key、返回非法 JSON、引用未知来源 ID 时，接口中断并清理本次已创建数据。
- AI 产生 1:N / N:1 / 差额补齐建议时，创建的 `MatchRecord`、`source_data` 和凭证分录一致。
- AI 不应复活用户明确驳回过的匹配。
- AI 重新分组时，旧单边任务的驳回/恢复逻辑可追溯。

**完成标准：** 覆盖成功、失败、隐私、非法输出、未知引用、用户驳回保护六类路径。

### Phase 5：前端工作台用户流审核

**测试目标：** 真实模拟操作员从来源台账进入凭证详情、调整、重配、合并、确认的关键路径。

**重点检查：**

- 来源台账筛选：来源状态、凭证状态、对方、日期、排序、分页。
- 点击银行/发票台账行后，能选中对应凭证；多凭证链接时进入聚合或明确选择。
- 凭证详情显示：来源明细、差额行、校验错误、分录预览、AI 原因、处理方式。
- 单边处理调整提交后，调用 `/api/vouchers/{id}/treatment-adjustment`，页面显示新科目和成功反馈。
- 重配弹窗支持单选和多选，已占用候选置灰且说明原因。
- 合并建议弹窗只提交显式 `source_voucher_ids`，成功后选中新合并凭证。
- 按钮事件不得把 `PointerEvent` 传进 API 路径。

**建议命令：**

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm test -- src/views/VoucherWorkbenchView.spec.js src/api/client.spec.js
npm run build
```

**浏览器验证目标：**

- 打开 `http://127.0.0.1:5174/vouchers`，选择真实企业和期间。
- 执行生成/刷新，观察可见成功反馈。
- 点击一条单边流水，查看处理建议，打开调整表单。
- 点击一条差额补齐凭证，确认差额来源行和分录方向。
- 点击确认按钮，验证 API 返回后状态变为已确认。

**完成标准：** 每个关键按钮至少有一次真实用户流验证；源码测试不能替代按钮点击和状态反馈。

### Phase 6：已确认凭证管理页审核

**测试目标：** 验证 `/voucher-management` 是已确认凭证浏览，不混入生成整理任务。

**重点检查：**

- API 调用必须带 `status=CONFIRMED`。
- 页面如收到混合状态数据，仍只展示已确认凭证。
- 默认 20 条分页，分页状态与总数一致。
- 凭证号、详情按钮都能打开 `记账凭证` 弹窗。
- 对方主体优先使用业务来源字段，发票来源缺少 `seller_name` / `buyer_name` 时使用 `source_data.invoice.counterparty_name` 兜底。
- 银行手续费显示 `银行收费`，不显示 `-` 或错误对方主体。

**建议命令：**

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm test -- src/views/VoucherManagementView.spec.js
```

**完成标准：** 管理页与工作台的职责边界清楚，已确认数据查询和详情展示通过自动化及浏览器验证。

### Phase 7：真实样本回归与问题归档

**测试目标：** 用真实导入数据发现自动化样本漏掉的业务问题。

**执行内容：**

- 选定一个真实工作包，记录银行流水数、发票数、匹配数、生成凭证数、待确认数、已确认数、驳回数。
- 导出或查询每张凭证的借贷总额，检查是否全部平衡。
- 按 `source_group_type` 聚合，确认每类场景数量合理。
- 抽样检查金额较大、差额不为 0、双向往来、银行手续费、同一对方多笔流水。
- 与会计样本或历史凭证表比对摘要、科目、金额方向。

**建议输出格式：**

```text
样本：企业 / 期间 / 工作包 ID
数据规模：银行流水 N、发票 M、匹配 R、凭证 V
异常汇总：P0 x 个、P1 x 个、P2 x 个、P3 x 个
重点发现：
- [P1] 场景 V04 销项收款大于发票时差额进入错误科目；样本凭证 ...
待确认问题：
- 某类银行摘要应归手续费还是平台扣费，需要业务确认
```

**完成标准：** 自动化测试和真实样本都跑过；所有问题有复现步骤和业务影响。

---

## 4. 本轮优先级建议

1. 先做 Phase 0、Phase 1、Phase 2。它们最可能发现错误记账、重复入账、差额方向等核心问题。
2. 再做 Phase 3、Phase 4。状态流和 AI 失败路径容易出现“测试看起来通过但数据被半写入”的问题。
3. 最后做 Phase 5、Phase 6、Phase 7。前端和真实样本验证用于确认操作链路和会计语义是否真正可用。

如果时间有限，最小专项包是：

- `test_voucher_service.py` 覆盖 V01-V14 的金额/科目矩阵。
- `test_voucher_api.py` 覆盖确认失败、驳回、重开、重配、合并、AI 失败清理。
- `VoucherWorkbenchView.spec.js` 覆盖调整、重配、合并、确认按钮路径。
- 浏览器验证 `/vouchers` 生成到确认、`/voucher-management` 点击凭证号打开详情。

---

## 5. 缺陷记录模板

```markdown
## [P级别] 简短标题

**场景：** Vxx / Phase x
**影响：** 错误记账 / 重复入账 / 状态误导 / UI 误导
**复现命令：** `cd ... && ...`
**复现步骤：**
1. ...
2. ...
3. ...
**期望：** ...
**实际：** ...
**证据：** 测试名、API 响应、截图或数据库记录
**初步定位：** 文件/函数
**是否需要业务确认：** 是/否
```
