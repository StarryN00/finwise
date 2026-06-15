# 简单登录鉴权设计

## 目标

生产部署后，为智税管家增加一层最小可用的登录保护，避免公网域名直接暴露业务页面和 `/api/*` 接口。

本方案只解决 Phase 1 的生产入口保护，不等同于完整权限系统。

## 当前范围

- 单一操作员账号登录。
- 登录成功后前端保存访问令牌。
- 前端请求 `/api/*` 时自动附带 `Authorization: Bearer ...`。
- 后端开启鉴权后保护所有 `/api/*` 业务接口。
- `/health`、`/api/auth/status`、`/api/auth/login` 保持公开。
- 开启鉴权后关闭 `/docs`、`/redoc`、`/openapi.json`。

## 环境变量

生产环境在 `.env` 中配置：

```bash
FINWISE_AUTH_ENABLED=true
FINWISE_ADMIN_USERNAME=operator
FINWISE_ADMIN_PASSWORD_HASH=替换为生成后的密码哈希
FINWISE_JWT_SECRET=替换为足够长的随机密钥
FINWISE_TOKEN_EXPIRE_HOURS=12
```

本地开发默认 `FINWISE_AUTH_ENABLED=false`，不影响现有调试流程。

## 密码哈希生成

```bash
cd /path/to/finwise/finwise-accounting/backend
source .venv/bin/activate
python - <<'PY'
from app.core.auth import hash_password
print(hash_password("替换成你的登录密码"))
PY
```

把输出写入 `FINWISE_ADMIN_PASSWORD_HASH`。不要把明文密码写进 git。

## 登录流程

1. 前端启动时访问 `/api/auth/status` 判断是否开启鉴权。
2. 未开启鉴权时，系统保持原来的访问方式。
3. 开启鉴权且没有本地令牌时，路由跳转到 `/login`。
4. 登录成功后，后端返回访问令牌和用户信息。
5. 前端保存令牌，后续 API 请求自动带上 Bearer Token。
6. API 返回 401 时，前端清理本地会话并跳转登录页。

## 后端规则

后端使用 PBKDF2-SHA256 保存密码哈希，令牌使用 HMAC-SHA256 签名。令牌只存储：

- 用户名
- 签发时间
- 过期时间
- token 类型

目前不写入企业、角色或菜单权限。

## 已知边界

- 暂不支持多用户。
- 暂不支持角色权限。
- 暂不支持登录审计日志。
- 暂不支持刷新令牌。
- 暂不支持账号锁定、验证码、二次验证。

这些能力应在后续“用户与权限中心”中统一设计，不建议在当前轻量登录层继续堆复杂逻辑。
