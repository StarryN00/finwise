# 凭证整理业务逻辑专项审核结果

执行日期：2026-06-05

## 执行范围

- 后端凭证服务与 API：`test_voucher_service.py`, `test_voucher_api.py`
- 前端凭证生成与管理页：`VoucherWorkbenchView.spec.js`, `VoucherManagementView.spec.js`, `client.spec.js`
- 只读数据审计脚本：`scripts/audit_voucher_sources.py`
- 浏览器验证：`http://127.0.0.1:5174/vouchers`, `http://127.0.0.1:5174/voucher-management`
- 真实样本：昆山黛珂特电子科技有限公司，2026-04，工作包 `42c5170e-c2a2-4b71-a54b-7189dd5039de`

## 自动化验证

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run pytest tests/test_voucher_service.py tests/test_voucher_api.py -q
```

结果：`71 passed`

覆盖：凭证服务/API 目标测试新增来源占用、确认保护、AI 预处理、合并建议回归。

```bash
cd /Users/starryn/project/finwise/finwise-accounting/frontend
npm test -- src/views/VoucherWorkbenchView.spec.js src/views/VoucherManagementView.spec.js src/api/client.spec.js
npm run build
```

结果：目标前端测试 `23 passed`，生产构建通过。

```bash
cd /Users/starryn/project/finwise/finwise-accounting/backend
uv run python scripts/audit_voucher_sources.py --package-id 42c5170e-c2a2-4b71-a54b-7189dd5039de --database-url sqlite:///./finwise_accounting.db
```

结果：脚本可复现真实样本重复来源和缺少来源分组类型问题，且不写入数据库。

## 已修复问题

### [P2] 差额补齐方向文案反了

**场景：** 组合来源凭证详情，`difference_amount > 0`

**影响：** 后端定义 `difference_amount = 发票合计 - 流水金额`。当发票金额大于流水时，前端显示为“流水金额大于发票，需补齐暂收/预付项目”，会误导操作员判断差额方向。

**证据：** 浏览器打开 2026-04 工作包首批差额补齐凭证，分录借 `1122 应收账款`，但来源明细文案曾显示“流水金额大于发票”。

**处理：**

- 新增 `VoucherWorkbenchView.spec.js` 回归测试，断言正差额显示“发票金额大于流水，需补齐应收/应付项目”。
- 修正 `VoucherWorkbenchView.vue` 的 `sourceBalanceLabel()` 正负映射。

**复验：**

- 新增测试先失败，修复后通过。
- 浏览器刷新工作台详情后显示“发票金额大于流水，需补齐应收/应付项目”，错误文案消失。

## 真实样本发现

### [P0/P1] 2026-04 工作包存在非驳回凭证重复占用同一来源

**场景：** 昆山黛珂特电子科技有限公司，2026-04，工作包 `42c5170e-c2a2-4b71-a54b-7189dd5039de`

**影响：** 同一银行流水或发票来源被多个非驳回凭证引用，可能造成重复处理或重复入账风险。该问题出现在本地样本数据中，可能是历史生成/重配遗留数据，也可能说明清理旧单边任务的逻辑需要补强。

**汇总：**

- 重复银行流水来源：2 个
- 重复发票来源：10 个
- 非驳回凭证均借贷平衡；本问题不是借贷不平，而是来源占用唯一性问题。

**银行流水重复样例：**

```text
16c63c49-b2e9-4afd-aac6-c3211c889a3c
- 记-0008 / 确认销售收入并收款 / CONFIRMED / match:c7863602-f050-4aaa-ab30-57a792db69c4
- 记-0010 / 确认多张销售发票并补齐收款差额 / CONFIRMED / group:4a83644290753c64a3ed794f

2f8b88ab-856c-472a-ac11-55b4e97a8ad5
- 记-0011 / 记录银行收款待补发票 / CONFIRMED / bank:2f8b88ab-856c-472a-ac11-55b4e97a8ad5
- 记-0012 / 确认多张销售发票并补齐收款差额 / CONFIRMED / group:793cd97f588c5fa6cbce104d
```

**发票重复样例：**

```text
03723b75-3f23-422e-8eec-3641789823d5
- 未编号 / 确认销售收入未收款 / PENDING_CONFIRMATION / invoice:03723b75-3f23-422e-8eec-3641789823d5
- 未编号 / 确认多张销售发票并补齐收款差额 / PENDING_CONFIRMATION / group:2f6ce62b37f397bf65d249d7
- 记-0010 / 确认多张销售发票并补齐收款差额 / CONFIRMED / group:4a83644290753c64a3ed794f
```

**本轮已补保护：**

- `generate_voucher_drafts()` 在生成 1:1、1:N、N:1 匹配凭证前，会检查来源是否已被已确认凭证或其他配对凭证占用。
- 若来源只被待确认单边凭证占用，生成匹配凭证前会先将旧单边凭证标记为 `REJECTED`，并写入 `SOURCE_REASSIGNED`。
- 单边银行手续费、未匹配发票、未匹配银行流水生成前，会按底层来源 ID 跳过已被非驳回凭证占用的来源，避免不同 `source_key` 造成重复草稿。
- `confirm_voucher()` 在写入凭证号前检查来源是否已被其他确认凭证占用；冲突时返回 `SOURCE_ALREADY_CONFIRMED`，保持待确认状态。
- AI 预处理不会为已确认来源或已有配对凭证来源创建 `MatchRecord`，也不会在后续生成阶段为该来源补出新的单边草稿。
- AI 合并建议会排除已被其他确认凭证或配对凭证占用的单边银行来源，避免前端继续推荐脏数据。
- 新增回归测试覆盖已确认单边阻止 1:1 匹配、待确认单边被重分配、已确认单边阻止组合匹配、确认时来源冲突拦截、AI 预处理来源占用拦截、AI 合并建议来源占用过滤六类路径。

**仍需后续处理：**

1. 当前真实样本已有重复来源，不能自动清理；需业务确认每组重复来源保留哪张凭证。
2. 业务确认后再提供一次性清理脚本：保留确认凭证或指定凭证，驳回重复的待确认单边/旧组合任务，并写入审计标记。
3. 清理后重新跑 `scripts/audit_voucher_sources.py`，目标为重复银行来源 0、重复发票来源 0。

## 其他观察

- 2026-04 工作包非驳回凭证借贷平衡检查未发现异常。
- 2026-04 工作包存在较多旧凭证缺少 `source_group_type`，导致部分关联凭证在来源台账里 `task_type` 退化为 `UNKNOWN`；这主要影响可解释性和筛选，不直接造成金额错误。
- 前端控制台存在 Element Plus `el-pagination small` 废弃警告；不影响本次业务逻辑。

## 新增工具

### 只读来源审计脚本

`scripts/audit_voucher_sources.py` 用于按工作包或全库输出凭证来源审计 JSON。

当前检查项：

- 各状态凭证数和非驳回凭证总数
- 非驳回凭证借贷是否平衡
- 同一银行流水 ID 被多个非驳回凭证占用
- 同一发票 ID 被多个非驳回凭证占用
- 缺少 `source_group_type` 的非驳回凭证数量和样例

示例：

```bash
uv run python scripts/audit_voucher_sources.py --package-id 42c5170e-c2a2-4b71-a54b-7189dd5039de --database-url sqlite:///./finwise_accounting.db
```
