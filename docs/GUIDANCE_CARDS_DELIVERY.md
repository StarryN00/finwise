# 处理建议卡与流水跨期接续交付

日期：2026-09-09。运行目录：`/Users/starryn/thinking/finwise-ontology-finance-system`。

## 已启用

- 原件及问题数据优先；后台建议、个人补充方案分开展示，不默认选择。
- Agent 输出只能引用已声明操作和有效证据；选择后仍须填写、核对摘要并明确提交。
- 支持“整理为处理方案”和仅本地保存意见。保存意见不触发模型、不会完成问题。
- 原件日期明确且同行读取一致的表格流水，可明确归属原交易月份。仅选择当前页记录，不任意改月份。
- 目标期间通过版本绑定的引用接续，不复制 FactRecord、不创建期间、不制证；可撤销，重复或依赖冲突拒绝。
- 版本、哈希、权限、Scope、幂等、来源校验继续生效。人工核实和账务可用口径不变。
- 后台复用持久化任务和既有单执行器；刷新、查看和切换企业不发起模型调用。

主要实现：`app/material_guidance.py`、`app/bank_periods.py`、任务 descriptor、service/API 与复核执行器集成；前端增加建议及跨期模块，复用原有详情与组内导航。未新增数据库表或独立业务路由。

## 实际验收

| 验证 | 实际结果 |
|---|---|
| Python 全量 | 885 passed；最终资源和首页等式另跑静态入口7项通过 |
| Node 全量 | 148 passed |
| 合成 Chromium | 建议/意见、失败保留、重试、明确勾选、接续/撤销、来源权限、三种宽度通过 |
| 隔离真实副本 | 页面执行 confirm_bank_period → accept_bank_period → revoke_bank_period_intake → revoke_bank_period 全链路通过 |
| 正式 DeepSeek | 隔离副本11次、Staging受控生成7次，共18次；26,529 tokens |
| 自由方案真实页面 | 返回 NEEDS_HUMAN，解释可见，可选择规则支持的归属操作；刷新恢复，无财务命令、无刷新调用 |
| 真实 Staging 页面 | 1440×900、1040×900、390×844只读导航通过；无业务写入 |
| 独立审查 | 日期错行、重复接续、个人结果隔离、首页统计等式问题已修复并回归；最终无阻塞项 |

实际正式模型并不保证返回可执行推荐。7个真实事项的模型调用均成功，但其中5项返回“尚需人工判断”，2项存在可执行候选；页面保留解释与程序支持的操作，不将低置信度当作业务确认。另有1项系统检查事项，不转成客户补资料任务。

调用响应未提供实际扣费金额，未用估算价格冒充账单。完整调用元数据见 [delivery.json](/Users/starryn/thinking/finwise-ontology-finance-system/output/guidance-cards/delivery.json)。11次隔离调用包含浏览器调试期间已成功返回、但页面断言失败的调用，未漏计费用用量。

## 真实数据保护与运行状态

- 8767已自动重启，PID 3464；原访问地址不变。
- 对比备份与当前库：原有对象及版本未改写，附件哈希保持一致；受保护的 `static/index.html`、`static/app.js` 未改。
- 真实环境只新增建议任务、模型调用及对应审计，不代用户保存意见、确认归属、接续或撤销。
- 未重解析、未导入3月、未生成凭证；真实环境没有自动创建2月期间。
- 当前记录统计仍为229条：系统检查通过219、需核对2、期间异常8，人工核实0、账务可用0。

备份：[pre-guidance-cards-2026-09-09T12-20-03+00-00](/Users/starryn/thinking/finwise-ontology-finance-system/data/backups/pre-guidance-cards-2026-09-09T12-20-03+00-00)。

## 使用与限制

打开问题详情，先查看来源，再选建议或填写自己的方案；核对选择及必填信息后明确提交。跨期确认后，在目标期“查看转出与接续”中逐条确认接续。

- 目前跨期确认只支持可重读、定位到同一行的表格银行流水；无法验证定位的PDF/扫描件不开放该操作。
- 自由文字采用严格本地意图脱敏。无法可靠脱敏的文字仅本地保存，不外发；并非任意自然语言都能映射执行。
- 多步建议不自动串行写入；当前操作完成后明确列出仍未执行步骤，需要逐步另行核对和提交。
- 归属/接续不代表目标期记账完成。已有其他异常、期初及业务证据门禁继续保留。

## 截图与证据

- [真实桌面1440](/Users/starryn/thinking/finwise-ontology-finance-system/output/playwright/guidance-cards-readonly-8767-1788956839998/source-1440.png)
- [真实窄桌面1040](/Users/starryn/thinking/finwise-ontology-finance-system/output/playwright/guidance-cards-readonly-8767-1788956839998/source-1040.png)
- [真实移动端390](/Users/starryn/thinking/finwise-ontology-finance-system/output/playwright/guidance-cards-readonly-8767-1788956839998/source-390.png)
- [个人方案页面](/Users/starryn/thinking/finwise-ontology-finance-system/output/playwright/guidance-custom-live/custom-1440.png)
- [跨期写入回归报告](/Users/starryn/thinking/finwise-ontology-finance-system/output/playwright/guidance-cards-isolated-write-8768-1788956314018/report.json)
- [个人方案真实模型回归](/Users/starryn/thinking/finwise-ontology-finance-system/output/playwright/guidance-custom-live/report.json)
- [Staging启用与保护记录](/Users/starryn/thinking/finwise-ontology-finance-system/output/guidance-cards/retained.json)

本轮按 task-pipeline 完成实现、验证及独立复核；使用 karpathy-guidelines 保持局部改造，awesome-design-md 保持原浅色层级，playwright 完成实际浏览器验收。
