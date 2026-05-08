<template>
  <div class="login-root">
    <!-- Left panel — brand -->
    <div class="login-brand">
      <div class="brand-bg-pattern"></div>
      <div class="brand-content">
        <div class="brand-logo">
          <svg width="52" height="52" viewBox="0 0 52 52" fill="none">
            <!-- 外圈圆环 -->
            <circle cx="26" cy="26" r="24" stroke="rgba(255,255,255,0.25)" stroke-width="2"/>
            <!-- 主体：圆角方块 + 向上的箭头，象征"收入/增长" -->
            <rect x="12" y="20" width="20" height="16" rx="3" fill="white" opacity="0.95"/>
            <!-- 方块内的折线，象征税单/报表 -->
            <path d="M16 30h4l2-3 4 5 4-6" stroke="#cc785c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
            <!-- 顶部小三角，象征"管家"屋顶/保护 -->
            <path d="M22 20V14l4-4 4 4v6" stroke="white" stroke-width="2" stroke-linejoin="round" fill="none" opacity="0.8"/>
          </svg>
        </div>
        <h1 class="brand-title">智税管家</h1>
        <p class="brand-subtitle">企业全生命周期服务 SaaS 平台</p>
        <div class="brand-features">
          <div class="feature-item">
            <span class="feature-icon">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <rect x="2" y="2" width="12" height="12" rx="2" stroke="rgba(255,255,255,0.8)" stroke-width="1.5"/>
                <path d="M5 6h6M5 8.5h4" stroke="rgba(255,255,255,0.8)" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
            </span>
            <span>发票智能管理</span>
          </div>
          <div class="feature-item">
            <span class="feature-icon">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M8 2v12M2 8l6-6 6 6" stroke="rgba(255,255,255,0.8)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                <circle cx="8" cy="11" r="2" fill="rgba(255,255,255,0.8)"/>
              </svg>
            </span>
            <span>税务智能申报</span>
          </div>
          <div class="feature-item">
            <span class="feature-icon">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <circle cx="8" cy="8" r="6" stroke="rgba(255,255,255,0.8)" stroke-width="1.5"/>
                <path d="M8 5v3.5l2.5 1.5" stroke="rgba(255,255,255,0.8)" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
            </span>
            <span>融资精准匹配</span>
          </div>
        </div>
      </div>
      <div class="brand-footer">
        <span class="mono text-muted" style="font-size:11px">FinWise v1.0</span>
      </div>
    </div>

    <!-- Right panel — form -->
    <div class="login-form-panel">
      <div class="login-card">
        <div class="login-card-header">
          <h2>欢迎回来</h2>
          <p>登录您的账户继续使用</p>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          class="login-form"
          @submit.prevent="handleLogin"
        >
          <div class="form-field">
            <label class="form-label">用户名</label>
            <el-input
              v-model="form.username"
              placeholder="请输入用户名"
              size="large"
              clearable
              :prefix-icon="UserIcon"
            />
          </div>

          <div class="form-field">
            <label class="form-label">密码</label>
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              size="large"
              show-password
              :prefix-icon="LockIcon"
              @keyup.enter="handleLogin"
            />
          </div>

          <div v-if="authStore.error" class="error-message">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            {{ authStore.error }}
          </div>

          <el-button
            type="primary"
            size="large"
            :loading="authStore.loading"
            class="login-btn"
            @click="handleLogin"
          >
            {{ authStore.loading ? '登录中...' : '登 录' }}
          </el-button>
        </el-form>

        <div class="login-hint">
          <span class="mono text-muted" style="font-size:11px">演示账号: admin / admin123</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, h } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const formRef = ref(null)

const UserIcon = h('svg', {
  width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', 'stroke-width': 2,
  innerHTML: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>'
})
const LockIcon = h('svg', {
  width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', 'stroke-width': 2,
  innerHTML: '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
})

const form = reactive({ username: '', password: '' })

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

const handleLogin = async () => {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
    const ok = await authStore.login(form.username, form.password)
    if (ok) router.push('/')
  } catch {}
}
</script>

<style scoped>
.login-root {
  display: flex;
  min-height: 100vh;
  background: var(--color-bg);
}

/* === Brand Panel === */
.login-brand {
  width: 480px;
  flex-shrink: 0;
  background: var(--color-accent);
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 48px;
  overflow: hidden;
}

.brand-bg-pattern {
  position: absolute;
  inset: 0;
  background-image:
    radial-gradient(circle at 20% 80%, rgba(255,255,255,0.08) 0%, transparent 50%),
    radial-gradient(circle at 80% 20%, rgba(255,255,255,0.06) 0%, transparent 50%);
}

.brand-content {
  position: relative;
  z-index: 1;
}

.brand-logo {
  margin-bottom: 24px;
}

.brand-title {
  font-size: 36px;
  font-weight: 800;
  color: white;
  letter-spacing: 4px;
  margin-bottom: 12px;
}

.brand-subtitle {
  font-size: 15px;
  color: rgba(255,255,255,0.75);
  margin-bottom: 48px;
}

.brand-features {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 12px;
  color: rgba(255,255,255,0.9);
  font-size: 14px;
}

.feature-icon {
  font-size: 18px;
}

.brand-footer {
  position: relative;
  z-index: 1;
}

/* === Form Panel === */
.login-form-panel {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
}

.login-card {
  width: 100%;
  max-width: 400px;
}

.login-card-header {
  margin-bottom: 36px;
}

.login-card-header h2 {
  font-size: 26px;
  font-weight: 800;
  color: var(--color-text-primary);
  margin-bottom: 8px;
}

.login-card-header p {
  font-size: 14px;
  color: var(--color-text-muted);
}

/* === Form Fields === */
.login-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  letter-spacing: 0.5px;
}

.error-message {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--color-danger-light);
  border: 1px solid var(--color-danger);
  border-radius: var(--radius-md);
  color: var(--color-danger);
  font-size: 13px;
}

.login-btn {
  width: 100%;
  height: 46px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 2px;
  margin-top: 8px;
  border-radius: var(--radius-md) !important;
}

.login-hint {
  text-align: center;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--color-border-light);
}
</style>