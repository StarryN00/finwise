# FinWise Staging 运行手册

## 范围

本环境只用于本机或局域网 Staging、真实 Gateway Harness 和聚贤达试点前验收。不得填写生产 DeepSeek Key、生产易代账账号或生产企业数据。

## 当前工作集：从 2025 历史账表接入 2026-01

按用户要求，当前本机 `127.0.0.1:8767/static/operator.html` 已切到一月，不再加载三月工作集。启动时须显式设置：

```bash
export FINWISE_DATABASE_PATH=/Users/starryn/thinking/finwise-ontology-finance-system/data/staging-juxianda-2026-01-from-2025/finwise.db
export FINWISE_STORAGE_PATH=/Users/starryn/thinking/finwise-ontology-finance-system/data/staging-juxianda-2026-01-from-2025/artifacts
```

继续保留认证和 Gateway 配置；不把 API Key 写入导入清单。操作账号不变，但旧会话不继承，需重新登录。该账号当前只获授权访问 `scope.json` 中的一月范围。

- 先接收 2025 全年序时账、余额表两份原件，资料截止期间为 `2025-12`，用途为历史参考。不是 `2026-02`，不视为已解析或已确认基线。
- 再接收 14 份一月资料；另保留一份 1—2 月公积金合并表，单独待核对，不提取为一月业务事实。
- 已提取 204 条记录：58 条已提取待核实、141 条需核对、5 条期间需确认；均不代表已核实。原件中的跨期行不得作为一月有效业务。
- 六份文件尚未被现有解析器正确提取，保留原件与具体失败提示；本轮未扩展历史账表、PDF 和其他原始表头适配器。
- 不继承旧模型输出、业务组、确认卡、凭证或交付包；本轮模型调用为零。Gateway 已配置不等于已执行本批分析。

导入清单位于当前数据目录的 `import-report.json`。重建脚本 `scripts/import_juxianda_january.py` 只接受不存在的新目录、精确的原件白名单，并拒绝文件或月份目录软链接；它不会清空旧库，也不执行备份或切换服务。再次运行前须先备份、确认新输出位置，不覆盖用户正在处理的数据。

原三月库和原件仍保留在 `data/staging-juxianda-2026-03-real-v2`；切换前完整备份位于 `data/backups/juxianda-before-january.rB8I5t`，SQLite 完整性与 14 份原件哈希已验证，备份与原库逻辑内容一致。早期一月导入校验副本另保留在 `data/backups/juxianda-january-initial-import`，不是当前运行数据。

下方三月 Harness 示例仅为此前验收记录，不应在当前一月工作集直接重跑。

## 启动前检查

1. 准备 Docker Compose。
2. 复制 `deploy/staging.env.example` 为 `deploy/staging.env`。
3. 仅在 `deploy/staging.env` 填写 Staging DeepSeek Key 和专用测试账号。
4. 确认 `FINWISE_REQUIRE_AUTH=true`、`FINWISE_ENVIRONMENT=staging`、`FINWISE_AGENT_MODE=gateway`。
5. 准备聚贤达 Scope JSON、业务组 ID 和 Staging 操作人授权。

## 启动与 Harness

```bash
docker compose -f deploy/docker-compose.staging.yml up -d --build
python3 scripts/run_real_agent_harness.py --preflight
python3 scripts/run_real_agent_harness.py \
  --scope-json /absolute/path/juxianda-2026-03-scope.json \
  --group-id '<existing-processing-group-id>' \
  --stage RULE_SUGGESTION \
  --replay \
  --report /absolute/path/staging-agent-report.json
```

Harness 必须输出 `mock: false`。报告不得包含 API Key、密码、企业名称或统一社会信用代码；只保留 Scope 期间、哈希、模型版本、证据 ID、Run ID 和错误码。

## 易代账闭环

1. 使用用户提供的实际导入模板和明确字段映射生成文件。
   导出对象必须包含人工确认的 `voucher_header`（凭证号、日期、摘要），适配器不会自动补齐。
2. 人工核对文件模板、科目映射、借贷合计、期间和凭证版本。
3. 导入指定测试账套。
4. 保存成功、失败或部分成功回执原文件。
5. 使用 `scripts/yidaizhang_adapter.py` 校验回执和 Manifest 绑定。
6. 通过既有 `ack_external_import` 命令写入系统。
7. 核对交付包、回执状态、凭证版本和来源证据。

没有实际模板或回执样例时，适配器必须停在“需要明确映射/样例”的阻断状态，不能凭字段名称猜测。

## 备份与恢复

```bash
sh deploy/backup_staging.sh /absolute/path/staging-backups
```

至少验证一次 SQLite 备份和原始资料卷可以在隔离目录恢复；未完成恢复演练不得进入下一阶段。

## 本轮完成边界

本手册不包含生产发布、生产数据库迁移、生产易代账导入或 L5 生产验收。它们需要单独的环境、权限、备份、回滚和授权记录。
