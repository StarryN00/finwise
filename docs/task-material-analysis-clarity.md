# task：第二步「资料分析」口径与归并改造

目标：让用户在第二步就能看清「已经好了多少 / 还剩什么 / 现在要做什么」，并让同类问题只处理一次。

基线：改动前请先跑一次全量测试并记录通过数，改完必须不低于该数。

---

## 背景：为什么要改

对当前代码（`readiness.py` 9-05、`operator.js` 9-06 23:30、`operator-materials.js` 9-06 23:38、`materials.py`）核对后确认四件事：

1. **好数字已经算出来了，落地页没用。** `state.overview.material_review.counts` 里已有 `awaiting_verification`、`source_verified`、`issue_tasks`、`accounting_usable`；落地页 `resultSummary()` 只用了 `state.overview.data_readiness.counts` 的旧四态，并且用 `usable_results.length` 显示"已核实可用"，在期初未确认时恒为 0。两份数据在同一个 payload 里。

2. **同类问题按文件被切开。** `materials.py` 的 `task()` 在 `for a in files.values()` 循环内构造，binding 含 `artifact_id`；`readiness.py` 的 `grouped_issues` 键是 `(aid, issue)`。实测 2026-03 的 440 条数据：58 条需复核记录**同一个原因**（银行流水无税率），因分散在多个文件被切成多条待办；全量问题类型只有 14 类。

3. **期初状态覆盖了本期资料的进度。** `service.py` 约 1769 行：当 `baseline_validation["status"] != "VALID"` 时，直接 `stage_items[1] = {**stage_items[1], "status": ..., "summary": historical_labels[...]}`，把「资料分析」这一格的摘要替换成历史核对状态。本期资料整理到什么程度被丢弃了。

4. **AI 在本步真实调用为 0。** `model_coverage.real_successful_calls` 判据是 `status=="SUCCEEDED" and gateway.mock is False`。当前第二步全部问题分类由确定性规则产出。

---

## 不得回退的性质

改动过程中以下任一条被破坏，本任务判定失败：

- **提取通过 ≠ 核实。** `readiness.py` 里那条注释所表达的原则必须保留：解析状态、模型建议、人工看过一眼，都不能把记录标成已核实。不得为了让"可用"数字好看而放宽 `CHECKED` / `SOURCE_VERIFIED` 的判定。
- **`accounting_usable` 的计算逻辑不变。** 它依赖 `state=='CHECKED'`、不在 `unusable` 集合、且 `valid_source` 为真。本任务只改它显示在哪里，不改它怎么算。
- **每个原件的哈希与版本校验必须逐一保留。** 见任务 B。
- 期初门禁不变：期初未确认时，制证与交付仍然不可继续。
- 不得删除或跳过既有测试来换取通过。

---

## 任务 A：落地页换口径

**改 `static/operator.js` 的 `resultSummary()`（约 150 行）。**

数据源从 `state.overview.data_readiness.counts` 换成 `state.overview.material_review.counts`（同一 payload 内已有，无需新增接口）。

主位显示三行，三者相加等于 `records`：

| 显示 | 取值 |
|---|---|
| 资料已整理好，可直接用 | `awaiting_verification + source_verified` 条（括注：其中人工已核实 `source_verified` 条） |
| 需要你决定 | `issue_tasks` 类（括注：涉及 `needs_review` 条） |
| 不属于本期 | `period_exceptions` 条 |

附注小字一行：`账务可用 {accounting_usable} 条 —— 期初确认后才会计入`。

要求：

- 「需要你决定」的主数字必须是**类数**（`issue_tasks`），不是条数。条数放括注。
- 「已核实可用 0 项」那一段从主位移除，其内容并入上面的附注小字。`usable_results` 的明细保留在下钻里。
- 三个主数字都要可点击下钻到对应记录清单（现有 `data-record-state` 机制可复用，注意状态名从 readiness 四态换成 materials 五态）。
- 面板标题「已得到什么」保留，但内容必须先给成果、后给待办。

---

## 任务 B：归并键从「文件+问题」改为「问题优先」

这是本任务里唯一有实质风险的一项，先读完再动手。

**现状**：`materials.py` 的 `task()` 在按文件的循环里构造，binding = `{artifact_id, version, sha256, records, kind, reason}`，`key = 'material-' + digest(binding)`。

**目标**：同一个 `reason` 跨多个原件的，合并为一条待办，一次处置覆盖全部记录。

**必须同时改写入路径**，否则会破坏安全校验。当前 `handle` 里两处都硬绑单个原件：

```python
task = next((t for t in overview['tasks'] if t['id']==value.task_id and t['artifact_id']==target), None)
...
if not self.source_valid(obj):   # 只校验了一个 obj
```

合并后一条任务跨多个原件，写入时必须：

1. binding 改为 `{reason, kind, sources: [{artifact_id, version, sha256}, ...], records: [...]}`，`sources` 按 artifact_id 排序后再 digest，保证键稳定。
2. **对 `sources` 里的每一个原件逐一执行 `source_valid` 校验**，任一不通过则整条拒绝，错误信息要指出是哪一份原件变了。不允许只校验第一个或只校验请求里带的那个。
3. `records` 的子集校验（`{r.object_id for r in refs}.issubset(task['record_ids'])`）保持不变。
4. 接口层不再要求请求绑定单一 `target` artifact；若为兼容保留该参数，必须校验它属于 `sources` 之一。

**同时改 `readiness.py`**：`grouped_issues` 的键从 `(aid, issue)` 改为 `issue`，组内保留 `artifact_ids` 与每个原件的记录数，供"按文件查看"使用。`categories[...]["issues"]` 的归属改为按该问题涉及的主要分类，或允许一条问题挂多个分类（择一实现，在 PR 说明里讲清楚选了哪种及原因）。

**前端**：`operator-materials.js` 默认按问题类型列出待办；提供"按原件查看"切换视图。合并后的待办卡片要显示：问题描述、涉及记录数、涉及原件数与文件名列表、金额合计（若可得）、一个处置动作。

---

## 任务 C：把期初从「资料分析」这一格里拆出去

**改 `service.py` 约 1768–1774 行。**

现在的做法是用历史核对状态**覆盖** `stage_items[1]`。改为：

- `stage_items[1]`（资料分析）始终反映**本期资料**的整理进度，不被期初状态覆盖。
- 期初/历史衔接作为一条独立的前置线返回（例如 `progress["prerequisite"] = {...}`，含状态、摘要、以及它阻断什么），前端单独一行展示。
- 前置线的文案必须明确写出影响边界：**阻断制证与交付，不阻断资料整理与核对**。
- `current_stage` 的推导不再因期初未确认而强制回到 `analysis`；改为：若本期资料尚未整理完，`current_stage` 自然停在 `analysis`；若已整理完但期初未确认，`current_stage` 前进到下一格，同时前置线显示为阻断。

前端主按钮相应调整：当前卡片讲哪条线，主按钮就属于哪条线，不允许出现"卡片讲期初、按钮跳本期资料"的错配。

---

## 任务 D：接入 AI，只做归并与提议，不做提取

**边界（硬性）**：AI 不参与字段提取与问题判定，这两件事继续由确定性解析和规则产出。已有的 `ModelRun` / `AgentSuggestion` / `ConfirmationCard` 三类对象作为落库载体。

AI 在本步只做三件事，产物一律是**建议**，不改变任何记录状态：

1. 对每一类合并后的问题，生成一句业务语言的说明，以及**一个可一次性执行的候选处置**（例："这 9 个银行户的手续费行都没有税率字段，建议统一按不涉税处理"）。
2. 对「归属或用途待确认」的原件与跨期记录，给出归属判断建议及依据。
3. 对同类问题给出处置方案候选清单，供人一次选择。

要求：

- 每条建议必须挂 `AgentSuggestion`，记录输入了哪些事实、模型版本、是否 mock；`model_coverage` 的统计口径不变。
- 建议被采纳时，落库的是**人的决定**，`AgentSuggestion` 只作为依据引用，不得直接翻转记录状态。
- 模型不可用或返回非法结构时，该类问题退回到纯规则描述，不阻断整个第二步。

---

## 任务 E：进度指标换口径

`operator.js` 进度面板现在显示"20% 已完成 1/5 阶段"并附"阶段进度，不代表数据核实比例"。

需要免责声明的指标就是错的指标。改为数据口径，例如：`440 条中 372 条已可直接使用，14 类待你决定`。阶段完成度可保留为次要信息，但不占主位，且不再需要那句免责声明。

---

## 验收标准

### 自动化

- 后端全量测试通过，总数不低于改动前基线。
- 新增测试覆盖：
  1. 落地页口径三数相加等于 `records`；期初未确认时"已整理好"仍为正数（这是本任务的核心目标，必须有测试锁住）。
  2. 同一 `reason` 跨 3 个以上原件时，合并为 1 条待办；`issue_tasks` 计数相应下降。
  3. 合并待办处置时，**任一涉及原件的 sha256 变化 → 整条拒绝**，且错误信息指出是哪一份。
  4. 期初未确认时，`stage_items[1]` 的摘要仍反映本期资料进度，不被历史状态覆盖；前置线单独返回且标明阻断范围。
  5. `accounting_usable` 在本次改动前后对同一份数据的取值完全一致（回归锁）。
  6. AI 不可用时，第二步仍可完整完成，问题清单退化为纯规则描述。

### 真实数据验证

用 `data/staging-juxianda-2026-03-real-v2` 那份 440 条数据跑一遍，记录：

- 改动前后「需要你决定」的类数变化（预期从按文件切分的组数下降到接近 14）
- 落地页三个主数字及其和
- `accounting_usable` 前后一致

并在 1 月那份真实数据上复跑一次（该库不在标准路径，请用运行实例实际使用的 `FINWISE_DATABASE_PATH`）。

---

## 执行顺序

A → C → E（都属于显示层，快速见效且互不冲突）→ B（有写入路径风险，单独提交、单独验证）→ D（独立）。

B 请单独一个提交，便于出问题时回退。
