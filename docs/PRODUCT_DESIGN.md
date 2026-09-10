# FinWise 智能财务系统产品设计文档

版本：v2.0  
设计类型：绿地产品设计  
设计目标：按照 Palantir Ontology 理念，建立智能化高、可控、稳定、可持续迭代的智能财务系统

当前期间工作台的资料结构、可信成果与任务交互，见 [资料就绪度产品设计](WORKBENCH_DATA_READINESS_DESIGN.md)。

## 1. 产品定位

FinWise 不是“上传资料后自动生成凭证”的工具，而是一个围绕企业真实业务运行的财税操作系统。

它需要让用户能够：

- 看到企业当前真实的财税状态
- 理解每一笔业务是如何形成的
- 查看业务与资料、发票、流水和凭证之间的关系
- 了解系统为什么做出某个判断
- 确认或否决系统提出的建议
- 只对满足条件的业务执行账务动作
- 在出现异常时继续处理安全业务
- 在未来月份复用已经确认的企业习惯

系统核心链路：

```text
企业与账套范围
→ 账套基线
→ 原始资料
→ 事实记录
→ 业务事实和业务事件
→ 可版本化业务处理组
→ 证据与判断
→ 规则与对账
→ 凭证版本
→ 分组交付
→ 外部回执
→ 期间归档
```

## 2. 产品设计目标

### 2.1 智能化

系统能够：

- 自动理解资料
- 识别业务事件
- 归并相关证据
- 发现异常和缺口
- 推荐处理规则
- 复用已确认的企业习惯
- 用自然语言回答业务问题

### 2.2 可控性

系统必须：

- 将事实、判断和动作分离
- 禁止 Agent 直接改写正式账务
- 对所有写操作设置权限和前置条件
- 让每个动作具备明确责任人
- 在证据不足或校验失败时阻断
- 将异常限制在具体业务范围内

### 2.3 稳定性

系统必须：

- 保证企业、账套、期间隔离
- 保留原始资料和历史版本
- 支持任务重试和结果重放
- 防止迟到结果污染新任务
- 保证业务组不会重复归属
- 保证外部交付结果可核对

### 2.4 可迭代性

未来新增税务、资产、资金、报表和经营分析功能时，不应重新解析所有文件，而应复用已有的业务对象、证据和关系。

## 3. Palantir Ontology 在 FinWise 中的对应关系

| Ontology 能力 | FinWise 对应设计 |
|---|---|
| Object | 企业、账套、期间、往来方、业务事件、业务处理组、凭证 |
| Property | 金额、日期、税额、状态、风险、有效期 |
| Link | 资料支撑业务、流水匹配发票、业务组生成凭证 |
| Action | 确认、暂挂、复核、生成草稿、交付、归档 |
| Policy | 权限、规则、证据要求、交付门禁 |
| Operational Workflow | 月结、对账、异常处理和分组交付 |
| Auditability | 来源、版本、责任人、时间和动作结果 |

关键区别：

> FinWise 的 Ontology 不只是描述对象，而是让对象可以被查询、判断、授权和执行动作。

## 4. 总体架构

```text
┌──────────────────────────────────────┐
│ 用户体验层                           │
│ 期间工作台 / 对象详情 / 确认卡 / 对话 │
└──────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────┐
│ 动作控制层                           │
│ Command API / 权限 / 门禁 / 审计      │
└──────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────┐
│ FinWise Ontology                     │
│ 对象 / 属性 / 关系 / 状态 / 动作      │
└──────────────────────────────────────┘
                    ↓
┌───────────────────┬──────────────────┐
│ 确定性规则引擎     │ 受控 Agent 层    │
│ 对账、税额、借贷   │ 分类、分组、解释 │
│ 期间、权限、门禁   │ 候选、风险、建议 │
└───────────────────┴──────────────────┘
                    ↓
┌──────────────────────────────────────┐
│ 事实与证据层                         │
│ 原始文件 / 标准记录 / 账套数据 / 日志  │
└──────────────────────────────────────┘
```

建议以关系型数据库作为交易事实和会计结果的主存储，再提供面向对象的 Ontology API 和关系查询层。搜索和向量检索只能辅助查询，不能成为会计事实的唯一来源。

## 5. 核心领域模型

### 5.1 Scope：所有对象的范围边界

所有对象必须明确归属：

```text
Tenant
→ Organization
→ LegalEntity
→ AccountingBook
→ AccountingPeriod
→ BaselineSnapshot
```

每个对象、关系、规则、任务、缓存、索引和 Worker 租约都必须携带 Scope。

最小范围字段：

```text
tenant_id
organization_id
legal_entity_id
ledger_id
accounting_period_id
baseline_id
```

任何查询都不能只依赖对象 ID，必须同时校验 Scope。

### 5.2 SourceArtifact：原始资料

代表用户上传或系统接收的原始文件。

包括：

- 银行流水文件
- 发票文件
- 工资表
- 合同
- 报销单
- 入库单
- 回单
- 余额表
- 序时账
- 外部系统导出文件

原始资料必须保存文件哈希、来源、上传人、接收时间、文件期间和解析版本，禁止被模型覆盖。

### 5.3 FactRecord：事实记录

代表从原始资料中解析出的结构化事实。

例如：

```text
银行流水：交易日期、金额、方向、对方账户、摘要、流水号
发票：发票号码、开票日期、购销双方、金额、税额、税率
工资记录：员工、应发工资、社保、公积金、个税、发放日期
```

FactRecord 只表达“资料中明确出现了什么”，不直接表达“这是什么业务”。

### 5.4 BusinessFact：稳定业务事实

代表跨 Run 持续存在的现实业务事实。

例如：

```text
某企业在 2026 年 3 月购买了一批设备
某企业在 2026 年 3 月向员工发放工资
某企业在 2026 年 3 月向供应商支付采购款
```

BusinessFact 不依赖文件行号、Agent Run 或 ProcessingGroup ID。

它必须支持稳定身份、来源证据、业务发生时间、会计归属期间、更正和冲销关系。

### 5.5 BusinessEvent：具体经济事件

代表 BusinessFact 中可以被处理的具体经济活动。

类型包括：

```text
PURCHASE
SALE
RECEIPT
PAYMENT
PAYROLL
TAX_PAYMENT
ASSET_ACQUISITION
ASSET_DISPOSAL
LOAN
TRANSFER
EXPENSE
OTHER
```

BusinessEvent 必须代表真实经济事项，不能只是发票记录、银行流水、Agent 任务或页面流程节点。

### 5.6 ProcessingGroup：账务处理组织

ProcessingGroup 是本次账务处理的业务组织单位。

例如：

```text
采购合同
+ 采购发票
+ 入库单
+ 银行付款
→ 一个采购 ProcessingGroup
```

ProcessingGroup 与 BusinessFact 不同：

- BusinessFact 表示现实业务
- ProcessingGroup 表示本次如何组织和处理该业务

相关对象：

```text
ProcessingGroup
ProcessingGroupRevision
GroupMembership
GroupLineage
GroupingDecision
SourceDisposition
```

同一业务补充资料、拆分、合并或更正时，必须创建新版本，不能原地修改。

### 5.7 Party：往来方

包括客户、供应商、员工、银行、税务机关、股东和关联方。

系统应区分：

```text
PartyIdentity：主体身份
PartyRelationship：主体在某企业中的业务关系
```

不能因为两个企业使用了相同名称，就默认它们是同一个业务主体。

### 5.8 Evidence：证据

Evidence 用于支撑某个事实、关系、判断或动作。

证据必须支持：

- 来源定位
- 页码、行号或字段定位
- 证据类型
- 完整性
- 独立性
- 是否过期
- 是否冲突
- 是否经过人工确认

证据等级：

```text
A：直接、完整、来源可靠
B：多个来源相互印证
C：资料部分缺失，可以形成待确认草稿
D：资料不足、相互矛盾或无法解释
```

## 6. 事实、判断与动作分层

FinWise 必须使用以下链路：

```text
FactRecord
→ Evidence
→ SemanticAssertion
→ AgentSuggestion
→ HumanDecision
→ RuleInstance
→ VoucherProposal
→ VoucherDraft
→ VoucherVersion
→ Command
→ EffectRecord
```

Agent 只能写入候选状态的 `AgentSuggestion` 和 `SemanticAssertion`，不能直接写入：

```text
BusinessFact
正式业务关系
RuleInstance
正式凭证
归档状态
锁账状态
```

## 7. 业务组身份、分组与谱系

### 7.1 稳定业务身份

BusinessEvent 的身份不能依赖文件行号或业务组 ID。

可以参考：

- 外部交易流水号
- 发票号码与销方组合
- 合同编号
- 工资批次号
- 资产编号
- 外部系统业务单号
- 业务日期、对方和金额组合特征

如果没有稳定的外部标识，系统只能建立候选业务身份，不能把系统生成的 ID 当成事实证明。

### 7.2 来源归属

每条事实记录必须有明确的处置状态：

```text
UNASSESSED
ASSIGNED
SPLIT
DUPLICATE
OUT_OF_SCOPE
SUSPENSE
```

同一期间、同一记账口径下，同一来源事实只能有一个有效主归属，但可以作为多个候选业务组的证据。

### 7.3 合并与拆分

以下动作必须产生新版本：

- 合并两个业务组
- 拆分一个业务组
- 替换业务证据
- 更正业务身份
- 改变业务期间
- 撤销原有匹配

必须记录原对象、新对象、变化原因、操作人、操作时间以及受影响的凭证和交付包。

## 8. 时间与版本模型

至少需要区分：

```text
valid_time       业务实际发生时间
accounting_time  会计归属期间
observed_time    系统发现或接收时间
decision_time    判断或确认时间
effective_time   规则或关系生效时间
close_time       期间关闭时间
```

必须支持跨期发票、期后补资料、以前年度调整、期初余额修订、已锁账期间冲销和新旧规则版本对比。

核心原则：

```text
新 Run 不能改写旧 Run 的历史结论
新规则不能追溯修改旧结果
已关闭期间不能被普通写操作修改
期初余额必须可追溯到上期关闭快照
```

## 9. 规则与企业习惯

规则生命周期：

```text
历史记录
→ RuleCandidate
→ ConfirmationCard
→ HumanDecision
→ RuleInstance
→ RuleVersion
```

RuleInstance 必须定义企业、账套、业务类型、往来方、有效期间、适用条件、例外条件、优先级、证据来源、确认人和撤销条件。

历史规则不能无条件套用。当前业务与历史规则不一致时，生成 `RuleConflict`，而不是继续强行匹配。

## 10. Agent 体系

### 10.1 资料理解 Agent

负责文件分类、字段提取、期间识别、记录标准化和缺失字段提示。

### 10.2 业务事件 Agent

负责判断业务类型、识别潜在经济事件、生成事件身份候选、发现重复和冲突。

### 10.3 关系与分组 Agent

负责推荐证据关联、推荐业务组、识别一笔多付、多笔一付、分期付款等关系，生成合并或拆分建议。

### 10.4 规则建议 Agent

负责推荐会计科目、税务处理、参考历史习惯、生成确认卡和解释规则冲突。

### 10.5 异常解释 Agent

负责解释阻断原因、指出缺少资料、汇总相似异常和提出补救建议。

Agent 不负责修改原始事实、直接确认业务事件、确认长期规则、生成正式凭证、自动导出、自动归档或自动锁账。

## 11. 置信度设计

不能使用单一的 `confidence >= 0.8` 作为记账放行条件。

建议记录：

```text
extraction_confidence
event_confidence
relationship_confidence
rule_fit_confidence
evidence_completeness
conflict_risk
deterministic_eligibility
human_approval
```

例如：

```text
模型置信度：0.95
证据完整性：不足
规则状态：未确认
对账状态：失败
最终状态：禁止交付
```

最终交付许可必须满足：

```text
基线通过
且证据满足要求
且规则已确认
且对账通过
且凭证复核完成
且操作人有权限
```

## 12. 确认卡与人工工作量

确认卡不能按单条流水生成，而应按以下粒度生成：

```text
规则批次
+ 业务处理组
+ 高风险异常
+ 首次业务模式
+ 规则冲突
```

批量确认必须满足：

```text
同一规则版本
+ 同一适用范围
+ 同一证据结构
+ 无冲突
+ 影响范围可预览
+ 操作可撤销
```

人工工作应从逐条录入和判断转变为确认规则批次、处理异常业务组和复核高风险凭证。

## 13. 对账与账务处理

### 13.1 ReconciliationCheck

必须支持银行流水与收付款、发票与业务金额、进销项税额、工资与社保公积金、期初与上期末、借贷平衡、业务组与凭证、期间一致性、重复记录和余额连续性检查。

每项检查保存检查对象、输入数据、检查公式、检查版本、容差、结果、失败原因和执行时间。

容差只能由财务政策定义，不能由 Agent 临时放宽。

### 13.2 凭证生命周期

```text
VoucherProposal
→ VoucherDraft
→ VoucherVersion
→ LocallyConfirmed
→ ExportCreated
→ ExternalAckPending
→ ExternalImported
→ PeriodClosed
→ PeriodLocked
```

必须区分 Agent 建议、凭证草稿、本地确认、导出包、外部导入、外部回执、期间关闭和期间锁定。

草稿不能进入正式余额和报表。

## 14. 命令授权层

所有写操作必须通过统一命令层：

```text
CommandIntent
→ AuthorizationDecision
→ PreconditionCheck
→ StateTransition
→ EffectRecord
→ AuditEvent
```

命令示例：

```text
confirm_baseline
approve_rule
confirm_grouping
suspend_group
rerun_group
generate_draft
validate_draft
revise_voucher
release_delivery
export_package
ack_external_import
close_period
lock_period
```

每个命令必须校验操作人、对象 Scope、对象版本、操作权限、前置条件、是否重复执行以及是否产生实际结果。

必须支持职责分离：

```text
基线确认
规则确认
凭证复核
导出
归档
锁账
```

## 15. 月结产品流程

```text
1. 选择企业、账套和期间
2. 建立处理范围
3. 确认账套基线
4. 接收原始资料
5. 解析并形成 FactRecord
6. 识别 BusinessFact 和 BusinessEvent
7. 建立证据和关系
8. 形成 ProcessingGroup
9. 生成规则确认卡
10. 人工确认必要规则
11. 执行对账校验
12. 生成凭证草稿
13. dry-run 和凭证复核
14. 安全业务组部分交付
15. 异常业务组补证或暂挂
16. 形成外部交付包
17. 接收外部回执
18. 形成期间归档包
19. 关闭或锁定期间
```

异常业务组不能阻塞所有安全业务组，但也不能被伪装成已完成。

## 16. 重新分析、重试与回放

重新分析必须新建 Run，固定输入资料范围、账套基线版本、规则版本、模型版本和 Schema 版本，同时保留旧 Run、旧业务组版本、旧凭证版本和旧审计记录。

重试必须从明确失败节点开始，使用新的尝试编号，校验对象版本，并防止迟到结果写入新版本。

系统必须能够使用以下内容重放历史 Run：

```text
输入资料版本
+ 账套基线版本
+ 规则版本
+ Prompt 或模型配置版本
+ Schema 版本
+ Gateway 版本
```

回放结果不得覆盖历史结果，只能生成新的比较结果。

## 17. 用户体验设计

### 17.1 期间工作台

首屏展示当前企业、账套、期间、真实处理状态、主要阻断原因、可交付业务组、待确认规则、异常业务组和一个主操作。

### 17.2 业务对象详情

用户进入的不是“文件详情”，而是业务对象详情：

```text
业务摘要
→ 来源资料
→ 关联证据
→ 业务关系
→ 历史相似记录
→ 适用规则
→ 对账结果
→ 凭证版本
→ 异常事项
→ 操作时间线
```

### 17.3 确认卡

确认卡必须先展示事实，再展示建议：

```text
原始证据
→ 系统匹配结果
→ 相似历史
→ 候选规则
→ 差异和风险
→ 用户动作
```

不能只展示“Agent 建议：记入某科目”。

### 17.4 对话入口

用户可以直接询问：

- 哪些采购未匹配付款？
- 这笔付款为什么暂挂？
- 哪些业务缺少入库证据？
- 哪些规则与历史不一致？
- 哪些业务组已经可以交付？
- 重新分析后发生了什么变化？

回答必须先查询结构化对象和关系，再让 Agent 解释。

## 18. 数据与技术架构

建议采用：

```text
关系型数据库
+ 原始文件存储
+ Ontology Object API
+ 关系查询层
+ 确定性规则引擎
+ Agent Gateway
+ 搜索索引
+ 审计事件流
+ 外部系统适配器
```

职责划分：

- 关系型数据库：事实、对象、状态、规则、凭证和交付结果
- 文件存储：原始资料和归档文件
- Ontology API：对象、关系和动作访问
- 规则引擎：金额、税额、期间、借贷和门禁
- Agent Gateway：脱敏、协议校验和调用隔离
- 搜索系统：对象和资料检索
- 向量系统：寻找相似案例，不作为会计事实来源
- 审计事件流：记录对象变化和动作结果
- 外部适配器：导出和接收外部系统回执

## 19. 安全与权限

权限层级：

```text
Tenant
→ Organization
→ LegalEntity
→ Ledger
→ AccountingPeriod
→ ProcessingGroup
→ Voucher
→ Evidence
```

必须实现数据库级 Scope 隔离、对象级权限、字段级敏感信息控制、Agent 输入脱敏、审计日志不可篡改、外部模型不可访问原始数据仓库、任务租约带 Scope，以及取消和超时任务的结果隔离。

## 20. 禁止事项

以下自动化必须禁止：

- 直接改写原始事实
- 仅凭置信度生成正式凭证
- 自动解决期间错配
- 自动吞掉对账差异
- 自动确认长期规则
- 用历史规则覆盖当前证据
- 没有外部回执就声明外部导入成功
- 将部分交付标记为完整归档
- 自动删除异常记录
- 让取消或超时任务的迟到结果继续写入
- 让不同企业共享未授权的规则和检索结果

## 21. 产品成功标准

### 数据基础

- 每个事实都有原始来源
- 每个对象都有稳定身份
- 每条关系都有依据
- 每次变化都有版本
- 每个对象都有完整 Scope

### 智能化

- Agent 能识别资料和业务事件
- Agent 能提出分组、规则和异常建议
- 已确认规则可以按条件复用
- 用户可以围绕对象直接查询和提问

### 可控性

- Agent 不能直接写正式账务
- 所有写操作都有命令授权
- 置信度不能单独放行
- 规则和凭证均可撤销或修订
- 异常不会污染安全业务组

### 稳定性

- Run 可重试、可回放
- 迟到结果不会污染新 Run
- 业务组不会重复归属
- 期间和企业不会串数据
- 外部交付可接收真实回执

### 可迭代性

- 新功能可以复用已有业务对象
- 税务、资产、资金和报表使用独立领域对象
- 新规则不会改写历史结果
- Agent、规则、数据和动作互不越权

## 22. 建议建设顺序

### 阶段一：本体词典与不变量

确定对象、属性、关系、Scope、时间、版本、状态、动作、权限和不变量。

### 阶段二：事实与证据层

建设：

```text
SourceArtifact
FactRecord
Evidence
SourceDisposition
Scope
AuditEvent
```

### 阶段三：业务语义层

建设：

```text
BusinessFact
BusinessEvent
EventIdentity
Party
ProcessingGroup
GroupMembership
GroupLineage
```

### 阶段四：规则与决策层

建设：

```text
SemanticAssertion
AgentSuggestion
Decision
ConfirmationCard
RuleCandidate
RuleInstance
RuleConflict
```

### 阶段五：账务与交付层

建设：

```text
ReconciliationCheck
VoucherProposal
VoucherDraft
VoucherVersion
DeliveryPackage
ExternalPostingAck
PeriodCloseSnapshot
```

### 阶段六：Agent 与用户体验

最后接入资料理解 Agent、业务事件 Agent、关系分组 Agent、规则建议 Agent、异常解释 Agent、对象工作台、确认卡和对话入口。

## 23. 最终产品定义

FinWise 的核心不是：

```text
AI 生成了多少张凭证
```

而是：

```text
系统是否知道这是什么业务
系统是否知道依据是什么
系统是否知道判断由谁确认
系统是否知道当前允许做什么
系统是否知道动作实际改变了什么
系统是否能在未来继续复用
```

最终产品应当成为：

> 一个以稳定业务事实为基础、以证据和关系为纽带、以财税规则为约束、以受控 Agent 为智能入口、以命令和审计为安全边界的智能财务操作系统。
