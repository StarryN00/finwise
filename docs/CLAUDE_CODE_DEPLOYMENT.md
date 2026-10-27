# Claude Code 接入与服务器部署

当前 8774 工作台所属代码是 `/Users/starryn/dev/finwise`。接入支持 **Codex CLI / Claude Code**；当前 Claude Code 的底层模型配置为 **DeepSeek V4.1 Flash**。另一旧项目的 DeepSeek harness 没有移植到此工作台，不把 Codex 选项标为 DeepSeek。Claude Code 是执行器，DeepSeek 是模型服务，两者可以组合。

## 使用方式

在期间工作台的“处理 Agent”选择执行器，点击“保存选择”或“切换并重新分析”。选择按企业/账套/期间/基线的完整 Scope 保存。无资料时只保存偏好；已有资料时建立新运行版本。处理中须先暂停。旧成果、原件和用户陈述保留；新运行完成前旧候选不可复核。

任务入队即固定执行器、模型、执行方式、轮次/超时/Claude 单次预算和镜像名称。执行和独立审查使用同一所选执行器、不同会话和工作目录。补充说明/资料、第4步处理选择均复用这套循环。CLI 成功退出不等于凭证通过；机械校验、独立审查覆盖、有效输入、权限和人工复核门禁保持有效。最终只是待复核 DRAFT，不自动过账或关账。

独立审查统一交付 `work/review.json`。系统兼容旧执行器的根目录 `review.json`；两处均存在但内容不同则反馈修复，不选择性采信其中一份。接收前仍检查冻结候选和原件、文件类型、审查覆盖及可复核凭证清单。审查引用支持字符串编号及带明确编号的说明对象；结构化说明完整保留，缺编号、重复编号及逐项未通过结论不会被当作有效通过清单。

## 本机开发

安装 Python 项目依赖与所选 CLI。当前使用 DeepSeek 的 Anthropic 兼容接口，不需要 Claude 账号或 `claude auth login`。已有 `FINWISE_DEEPSEEK_API_KEY` 自动复用；也可用 `FINWISE_CLAUDE_API_KEY` 给执行器配置独立的 DeepSeek Key。

```dotenv
FINWISE_CLAUDE_BASE_URL=https://api.deepseek.com/anthropic
FINWISE_AUTONOMOUS_CLAUDE_MODEL=deepseek-flash[1m]
# FINWISE_DEEPSEEK_API_KEY 在服务器私密配置中填写，不提交代码。
```

配置依据：[DeepSeek 官方 Claude Code 接入说明](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code)与[Anthropic API 兼容说明](https://api-docs.deepseek.com/guides/anthropic_api/)。当前 Key 的模型列表已核实 `deepseek-flash` 对应 **DeepSeek-V4.1-Flash**（`[1m]` 为 Claude Code 上下文配置后缀）；显式指定模型，避免未知模型名被服务商映射到其他模型。内部辅助调用同样映射到 DeepSeek。

2026-09-27 已将本地运行配置和服务器部署示例切换为 V4.1 Flash。配置生效后新建任务的分析与独立审查均使用 Flash；已完成任务保留当时固定的模型标签和成果，不因切换自动重跑。此前 V4 Pro 验收记录仍保留为历史证据。

`.env` 相关配置见 `.env.example`。本机默认执行器仍为 `codex`，可在网页选择 Claude Code；服务器示例默认 Claude Code。密钥不会写入任务对象、命令参数、浏览器或运行快照。模型名及接口由服务端配置，API 只接收允许的执行器枚举。接口变化时旧任务受阻，建立新任务后执行，防止将新接口的凭据发到旧接口。

如需使用原生 Claude 模型，将接口改为 `https://api.anthropic.com`、模型改为 `sonnet`，配置 Anthropic Key；只在本机开发且不配置 API Key 时使用 Claude 订阅登录。DeepSeek Key 不会被自动转发到其他域名。

本机执行只限 development：现有 Codex workspace-write 与 Claude 工具许可不能替代完整读取隔离。

## Linux 服务器

提供独立的 `deploy/docker-compose.autonomous.yml`，旧 staging 部署文件不变。应用与 Agent 任务镜像一起构建、由应用后台自动启动，无需桌面 Codex App 或人工打开 Claude 会话。

前提：Linux、Docker Engine、Docker Compose v2；服务器能访问镜像/npm/Python 依赖仓库及所配置的模型 API。模型凭据由部署方提供；镜像不带本机订阅登录、客户数据或密钥。

```bash
cp deploy/autonomous.env.example deploy/autonomous.env
chmod 600 deploy/autonomous.env
# 在该文件中配置 FINWISE_DEEPSEEK_API_KEY；不要将密钥写入聊天或命令历史。
# 下述变量给 Compose 做宿主机路径和 Docker socket 权限映射。
export FINWISE_DATA_ROOT=/srv/finwise
export FINWISE_DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)
sudo install -d -o 10001 -g 10001 "$FINWISE_DATA_ROOT"
docker compose -f deploy/docker-compose.autonomous.yml --profile build build
docker compose -f deploy/docker-compose.autonomous.yml up -d finwise
```

默认监听 `127.0.0.1:8766`，外部访问经已有 HTTPS 反向代理。认证强制开启，无默认账号；用同一容器、同一数据库执行 `scripts/manage_access.py create-user` / `grant-scope`（交互式输入密码），参见 README。不要用 `serve_autonomous.py` 部署公网，它是关闭认证的本地验收入口。

应用使用 SQLite 持久目录及原件子目录。没有将本机数据库迁移到服务器；若未来迁移，须另行备份和验证。应用以 UID 10001 运行，持久目录应归此用户所有。

### 执行隔离与凭据

每次 worker/reviewer 启动一个短生命周期容器：只挂当前运行目录，原件、工具、合同、上下文以及独立审查候选覆盖为只读；根文件系统只读，临时目录可写，删除 capabilities，限制 CPU/内存/PID。任务不挂数据库、其他企业目录、Docker socket、主机 HOME 或应用配置；只传所选模型专用凭据。

`FINWISE_AUTONOMOUS_HOST_RUN_ROOT` 是宿主机持久目录下的 `autonomous-runs`，Compose 自动配置它；容器中的对应目录是 `/var/lib/finwise/autonomous-runs`。不是让 API 或 Agent 指定宿主机路径。

**应用控制器**需要访问宿主机 Docker socket 来创建任务容器，因此它是受信任的运维组件，拥有较高宿主机权限；不要把 socket 暴露给用户或 Agent。此部署适用于受控单机服务，不宣称完成共享宿主机的全面多租户安全认证。

Claude 容器使用 `--bare` 和专用 API Key；忽略主机的插件、Hooks、MCP、自动记忆和交互配置。服务器 Codex 选项需要独立配置 `FINWISE_CODEX_API_KEY`。未配置的选项显示“未配置”并禁止选择；模型鉴权、限流或预算失败属于系统受阻。

容器中的 Codex 由外层容器提供文件隔离，采用 danger-full-access 执行策略，避免嵌套 Linux sandbox 无法工作；这不放开宿主机访问。Claude 采用 dontAsk，仅启用处理所需的文件和 Bash 工具。两套执行器都不能直接调用系统写账接口。

### 超时、取消与费用

CLI 由后台任务监控，暂停/撤权/输入变化会停止进程并回收任务容器；外层硬超时在应用异常退出时仍限制任务持续时间。租约及迟到拒收继续生效，服务重启可恢复有界任务。

`FINWISE_CLAUDE_BUDGET_USD=0` 是默认值：不向 Claude Code 传费用硬上限，避免处理到一半因估算费用中断；如部署方明确设置正数才启用该上限。成功和失败的 CLI 估算用量均记录，DeepSeek 实际费用仍以其账单为准。技术超时、取消和审查门禁继续有效；费用不决定业务是否完成。

临时网络、限流及执行超时会保留工作文件并自动接续，同一任务最多尝试3次（含首次执行）；认证无效等无法自行修复的问题仍明确报告。恢复及手动继续仅复用同一输入指纹、同一模型/接口的工作文件，检查旧冻结原件与文件安全；重新生成只读工具、重做机械校验和独立审查，绝不复用旧通过状态。若已交付并校验过完整候选，可直接接续到重新校验和新会话独立审查，无需重复资料分析。处理中显示上一轮成果数量和记录入口，旧候选仍不能作为当前成果确认。

## 验收

```bash
python scripts/verify_autonomous_executor.py --backend claude_code --output /absolute/new-test-directory
```

脚本使用合成银行手续费原件和独立测试账套，真实调用 Agent、机械校验、独立审查和候选落库。失败返回非零状态；不进入现有客户账套、不正式过账。加 `--execution-mode docker` 可在已配置模型凭据和任务镜像的环境验证完整容器流程。

代码回归、浏览器固定测试结果、镜像/隔离验证及真实模型业务验证必须分别记录。鉴权未恢复或服务器 Key 未提供时，不声称完成真实 Claude 财务能力验收。

部署后可在应用容器中用独立合成账套验收。宿主目录映射须显式指定，不能把容器路径当宿主路径：

```bash
docker compose -f deploy/docker-compose.autonomous.yml exec finwise \
  python scripts/verify_autonomous_executor.py --backend claude_code --execution-mode docker \
  --output /var/lib/finwise/claude-verification \
  --host-run-root /srv/finwise/claude-verification/autonomous-runs
```

上述 `/srv/finwise` 须与实际 `FINWISE_DATA_ROOT` 一致；每次验收使用新目录。

### 2026-09-26 实测结果

Claude Code 2.1.123 + DeepSeek V4 Pro 在 Docker 中完成合成银行原件处理、机械校验、独立审查和 DRAFT 落库：1 轮通过，1 张凭证，日期 2026-08-03，借贷各 10.00，与原件一致。执行和审查的真实响应模型均为 `deepseek-v4-pro`，未使用 Claude 订阅登录；不代表整月客户业务已完成。服务器镜像启动、认证门禁和配置检查通过，尚未部署到远程服务器。

处理过程、真实运行证据和限制见 `output/claude-deepseek-20260925/处理与验收记录.md` 与 `acceptance-summary.json`。界面已将荣鼎坤 8 月任务按新配置建立为第15轮，后台继续处理。

### 2026-09-26 同日后续：取消费用硬上限与真实客户验收

按用户要求将单次费用上限设为0，补充中间成果恢复和结构化审查引用兼容。荣鼎坤7份原件第18轮已完成机械校验、独立审查及候选接收：40张凭证完成评估，7张DRAFT进入第4步，33张有待决事项，系统受阻0张；重启服务后仍保持完成状态。本轮是基于已提供本期账的原账复核，未正式过账。完整回归1375项、前端26项通过。详见 `output/continuous-processing-20260926/处理与验收记录.md` 与 `acceptance-summary.json`。
