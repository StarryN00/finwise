<template>
  <div class="login-root">
    <!-- Left panel — brand -->
    <div class="login-brand">
      <div class="brand-bg-pattern"></div>
      <div class="brand-content">
        <div class="brand-logo">
          <svg width="56" height="56" viewBox="0 0 56 56" fill="none">
            <rect width="56" height="56" rx="16" fill="rgba(255,255,255,0.15)"/>
            <path d="M14 40V24l14-8 14 8v16l-14 8-14-8z" fill="white" opacity="0.9"/>
            <path d="M28 16v24M14 24l14 8 14-8" stroke="white" stroke-width="2.5" fill="none"/>
          </svg>
        </div>
        <h1 class="brand-title">智税管家</h1>
        <p class="brand-subtitle">企业全生命周期服务 SaaS 平台</p>
        <div class="brand-features">
          <div class="feature-item">
            <span class="feature-icon">📋</span>
            <span>发票智能管理</span>
          </div>
          <div class="feature-item">
            <span class="feature-icon">📊</span>
            <span>税务智能申报</span>
          </div>
          <div class="feature-item">
            <span class="feature-icon">💰</span>
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