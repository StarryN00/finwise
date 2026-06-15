# FinWise Accounting 启动说明

`finwise-accounting/` 是智税管家代账月度工作台的新系统目录。旧版根目录 `backend/`、`frontend/` 不属于本次重建系统，其他设备同步代码后请从本目录启动。

## 1. 环境要求

- Python 3.11 或以上
- Node.js 20 或以上
- npm
- Git

可选：

- Kimi / Moonshot API Key：用于 AI 匹配、AI 凭证预处理、健康报告生成。
- Chromium Playwright 运行时：用于财务健康报告 PDF 渲染。

## 2. 拉取代码

```bash
git clone git@github.com:StarryN00/finwise.git
cd finwise/finwise-accounting
git checkout feature/phase1-completion
git pull
```

如果已经 clone 过：

```bash
cd /path/to/finwise
git checkout feature/phase1-completion
git pull
cd finwise-accounting
```

## 3. 后端安装与启动

进入后端目录：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
python -m playwright install chromium
```

创建环境变量文件。后端会读取 `finwise-accounting/.env`、`finwise-accounting/backend/.env` 等位置，推荐放在 `finwise-accounting/.env`：

```bash
cd /path/to/finwise/finwise-accounting
touch .env
```

`.env` 示例：

```bash
DATABASE_URL=sqlite:///./finwise_accounting.db
ENABLE_AI=true
MOONSHOT_API_KEY=你的_kimi_api_key
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
MOONSHOT_MODEL=moonshot-v1-32k
MOONSHOT_REPORT_MODEL=moonshot-v1-8k
AI_MATCH_CONFIDENCE_THRESHOLD=90
```

生产环境建议开启登录鉴权：

```bash
FINWISE_AUTH_ENABLED=true
FINWISE_ADMIN_USERNAME=operator
FINWISE_ADMIN_PASSWORD_HASH=替换为生成后的密码哈希
FINWISE_JWT_SECRET=替换为足够长的随机密钥
FINWISE_TOKEN_EXPIRE_HOURS=12
```

生成密码哈希：

```bash
cd /path/to/finwise/finwise-accounting/backend
source .venv/bin/activate
python - <<'PY'
from app.core.auth import hash_password
print(hash_password("替换成你的登录密码"))
PY
```

说明：

- 不配置 `DATABASE_URL` 时，默认使用本地 SQLite：`backend/finwise_accounting.db`。
- 不配置 `MOONSHOT_API_KEY` 时，AI 相关功能会失败或进入非 AI 兜底逻辑。
- 本地开发默认不启用登录鉴权；生产环境设置 `FINWISE_AUTH_ENABLED=true` 后，除健康检查和登录接口外，所有 `/api/*` 都需要登录。
- 开启鉴权后，后端 `/docs`、`/redoc`、`/openapi.json` 会关闭，避免生产环境暴露接口文档。
- `.env` 不要提交到 git。

启动后端：

```bash
cd /path/to/finwise/finwise-accounting/backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

验证后端：

```bash
curl http://127.0.0.1:8001/health
```

预期返回：

```json
{"status":"ok"}
```

## 4. 前端安装与启动

新开一个终端：

```bash
cd /path/to/finwise/finwise-accounting/frontend
npm install
npm run dev
```

前端默认地址：

[http://127.0.0.1:5174](http://127.0.0.1:5174)

Vite 已配置代理：

- 前端 `/api/*`
- 自动转发到 `http://127.0.0.1:8001`

所以本地开发时需要同时启动：

- 后端：`127.0.0.1:8001`
- 前端：`127.0.0.1:5174`

## 5. 推荐启动顺序

```bash
# 终端 1：后端
cd /path/to/finwise/finwise-accounting/backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

```bash
# 终端 2：前端
cd /path/to/finwise/finwise-accounting/frontend
npm run dev
```

然后浏览器打开：

```text
http://127.0.0.1:5174
```

## 6. 数据说明

默认本地数据库是 SQLite。首次启动后端时会自动建表，但不会自动导入业务数据。

如果你希望复用另一台设备上的测试数据，可以复制数据库文件：

```bash
finwise-accounting/backend/finwise_accounting.db
```

复制到新设备同一路径后再启动后端。

如果没有复制数据库，需要在系统里重新：

1. 新增企业
2. 初始化期初利润表、资产负债表
3. 创建月度工作包
4. 导入银行流水、进项发票、销项发票
5. 执行 AI 预处理、凭证确认、账簿和报表生成

上传文件会保存在：

```bash
finwise-accounting/backend/storage/
```

该目录是本地开发数据，不建议提交到 git。

## 7. 测试命令

后端测试：

```bash
cd /path/to/finwise/finwise-accounting/backend
source .venv/bin/activate
pytest -q
```

前端测试：

```bash
cd /path/to/finwise/finwise-accounting/frontend
npm run test
```

前端构建：

```bash
cd /path/to/finwise/finwise-accounting/frontend
npm run build
```

## 8. 常见问题

### 8.1 前端打开后接口 404 或 500

先确认后端是否启动：

```bash
curl http://127.0.0.1:8001/health
```

再确认前端访问的是：

```text
http://127.0.0.1:5174
```

不要直接打开 `dist/index.html`，开发环境需要 Vite 代理 `/api`。

### 8.2 上传 `.xls` 银行流水失败

后端需要 `xlrd>=2.0.1`。重新安装后端依赖：

```bash
cd /path/to/finwise/finwise-accounting/backend
source .venv/bin/activate
pip install -e ".[test]"
```

### 8.3 生成健康报告 PDF 失败

先安装 Playwright Chromium：

```bash
cd /path/to/finwise/finwise-accounting/backend
source .venv/bin/activate
python -m playwright install chromium
```

再确认 `.env` 中存在：

```bash
MOONSHOT_API_KEY=...
```

### 8.4 AI 预处理没有响应或失败

确认 `.env`：

```bash
ENABLE_AI=true
MOONSHOT_API_KEY=...
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
MOONSHOT_MODEL=moonshot-v1-32k
```

然后重启后端。环境变量修改后，正在运行的 `uvicorn` 不会自动重新读取所有配置。

### 8.5 端口被占用

后端默认端口是 `8001`，前端默认端口是 `5174`。

查端口占用：

```bash
lsof -i :8001
lsof -i :5174
```

结束占用进程后重新启动。

## 9. 开发边界

- 新系统代码在 `finwise-accounting/`。
- 不要把旧版根目录 `backend/`、`frontend/` 的改动混入新系统提交。
- 不要提交 `.env`、本地数据库、上传文件、构建产物和 Playwright 临时目录。
- UI 文案使用中文；代码、API 命名使用英文。
