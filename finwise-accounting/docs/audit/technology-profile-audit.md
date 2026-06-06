# 企业科技资质画像审计记录

日期：2026-05-25

## 本次完成内容

- 新增企业科技资质画像后端模型、服务和 API。
- 企业名册增加“科技画像”列，展示扫描状态、关键科技资质和知识产权摘要。
- 企业详情增加“科技资质画像”区块，展示科技认证、知识产权、服务机会、证据和人工确认/驳回入口。
- 新增结构化 JSON 导入脚本，用于把 Codex skill 或人工整理的采集结果写回系统。
- 新增企查查扫描/复查种子脚本，当前用于给现有真实企业生成可复核画像记录。
- 新增本地 Codex skill：`/Users/starryn/.codex/skills/finwise-technology-profile-scan`，用于后续增量扫描触发和操作约束。

## 当前企业画像填充情况

| 企业 | 状态 | 说明 |
|---|---|---|
| 昆山黛珂特电子科技有限公司 | 待确认 | 已撤回复查种子中的命中判断；科技资质和知识产权需以企查查科创分弹窗结构化文本重新确认 |
| 昆山晟立烁科技有限公司 | 待确认 | 未自动取得可确认科技资质，已标记为需企查查/天眼查复查 |
| t | 未扫描 | 测试企业，未填充业务画像 |

## 安全边界

- 未在代码、测试、日志或审计文档中记录企查查/天眼查账号密码。
- 当前 `.env` 未发现可解析的标准 `KEY=VALUE` 凭据项，因此未执行自动登录采集。
- 本次没有保存平台原始 HTML、cookie、截图或敏感中间文件。

## 验证结果

```bash
cd finwise-accounting/backend
.venv/bin/pytest
```

结果：`118 passed`

```bash
cd finwise-accounting/frontend
npm test -- --run
npm run build
```

结果：`20 passed`，构建成功。

## 浏览器验证

- 企业名册可见“科技画像”列。
- 昆山黛珂特电子科技有限公司显示“待确认”和关键标签“科技型中小企业、高新技术企业”。
- 企业详情可见“科技资质画像”区块、证据列、确认/驳回按钮。
- 本地 skill 校验通过：`Skill is valid!`

## 2026-05-25 复核修正

用户指出截图和系统画像不一致后，已完成以下修正：

- 增加企查查科创分文本解析器，支持解析 `HIT`、`NOT_HIT` 和知识产权数量。
- 结构化导入脚本支持 `qichacha_innovation_text` 字段，后续只要拿到企查查弹窗可见文本即可自动更新画像。
- 复查种子不再写入 `HIT`，避免把未核验数据输出给银行或代账端。
- 已把现有复查种子生成的黛珂特正向标签降级为 `PENDING_REVIEW`。
- 尝试通过 Chrome 扩展读取企查查页面 DOM 和剪贴板文本，但页面脚本环境超时，未使用截图手工纠正数据。

验证：

```bash
cd finwise-accounting/backend
.venv/bin/pytest tests/test_qichacha_innovation_parser.py tests/test_technology_profile_import_script.py tests/test_technology_profile_api.py -v
```

结果：`7 passed`

## 后续建议

- 将企查查/天眼查真实页面解析沉淀为 Codex skill。
- 凭据建议使用本地 `.env` 标准键名或系统钥匙串，不通过聊天发送。
- 贷款评分模块实现时，读取已确认标签并对待确认/过期标签降权。

## 2026-05-25 批量扫描任务改造

用户确认单家粘贴不适合生产后，已完成批量扫描 MVP：

- 新增 `TechnologyScanJobItem`，用于记录每家企业在批量扫描任务中的状态。
- 完善 `TechnologyScanJob`，支持扫描范围、需人工处理数、创建人和更新时间。
- 新增批量任务 API：创建任务、查询任务、标记单家运行、完成、失败和暂停。
- 企业名册新增“批量扫描科技画像”和“查看扫描任务”入口。
- 批量任务抽屉展示任务状态、企业数、单家企业状态和失败原因。
- 新增本地采集器骨架 `scripts/run_technology_scan_job.py`，用于后续接入企查查/天眼查登录态浏览器采集。
- 验证码、登录失效、主体重名、未找到科创分等场景均留痕为需人工处理或暂停，不写成命中标签。

验证：

```bash
cd finwise-accounting/backend
.venv/bin/pytest -q
```

结果：`128 passed`

```bash
cd finwise-accounting/frontend
npm test -- --run
npm run build
```

结果：`20 passed`，构建成功。

浏览器验收：

- 企业名册可见“批量扫描科技画像”和“查看扫描任务”。
- 扫描任务抽屉可打开。
- 未选择企业时创建“未扫描企业”任务成功。
- 任务抽屉展示任务总数、状态、企业明细和详情入口。
