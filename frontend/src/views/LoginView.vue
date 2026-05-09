<template>
  <div class="login-root">
    <!-- Left panel — brand -->
    <div class="login-brand">
      <div class="brand-bg-pattern"></div>
      <div class="brand-content">
        <div class="brand-logo">
          <svg width="52" height="52" viewBox="0 0 52 52" fill="none">
            <circle cx="26" cy="26" r="24" stroke="rgba(255,255,255,0.25)" stroke-width="2"/>
            <rect x="12" y="20" width="20" height="16" rx="3" fill="white" opacity="0.95"/>
            <path d="M16 30h4l2-3 4 5 4-6" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
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
        <span class="mono" style="font-size:11px; color: rgba(255,255,255,0.5);">FinWise v1.0</span>
      </div>
    </div>

    <!-- Right panel — form -->
    <div class="login-form-panel">
      <div class="login-card">
        <div class="login-card-header">
          <div class="login-eyebrow mono">FinWise · 智税管家 · LOGIN</div>
          <h2 class="login-title">欢迎回来</h2>
          <p class="login-desc">登录您的账户继续使用</p>
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
              class="login-input"
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
              class="login-input"
              @keyup.enter="handleLogin"
            />
          </div>

          <div v-if="authStore.error" class="error-message">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            {{ authStore.error }}
          </div>

          <button
            type="submit"
            class="btn primary login-btn"
            :disabled="authStore.loading"
          >
            {{ authStore.loading ? '登录中...' : '登 录' }}
          </button>
        </el-form>

        <div class="login-hint">
          <span class="mono" style="font-size:11px; color: var(--mute);">演示账号: admin / admin123</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const formRef = ref(null)

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
  background: var(--bg);
}

/* === Brand Panel === */
.login-brand {
  width: 480px;
  flex-shrink: 0;
  background: var(--accent);
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

.brand-logo { margin-bottom: 24px; }

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

.feature-icon { font-size: 18px; }

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

.login-eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.22em;
  color: var(--accent);
  text-transform: uppercase;
  margin-bottom: 12px;
}

.login-title {
  font-size: 88px;
  font-weight: 600;
  letter-spacing: -0.028em;
  color: var(--ink);
  line-height: 0.95;
  margin-bottom: 16px;
}

.login-desc {
  font-size: 14px;
  color: var(--mute);
  line-height: 1.5;
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
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-2);
  letter-spacing: 0.05em;
}

/* Use custom underline input style — override el-input */
.login-input :deep(.el-input__wrapper) {
  border-radius: 0 !important;
  box-shadow: none !important;
  border-bottom: 1px solid var(--line) !important;
  background: transparent !important;
  padding: 4px 0 !important;
}
.login-input :deep(.el-input__wrapper:hover) {
  box-shadow: none !important;
  border-bottom-color: var(--ink) !important;
}
.login-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: none !important;
  border-bottom-color: var(--accent) !important;
}
.login-input :deep(.el-input__inner) {
  font-size: 15px;
  color: var(--ink);
  height: 36px;
}

.error-message {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--alert-bg);
  border-radius: 8px;
  color: var(--alert-fg);
  font-size: 13px;
}

.login-btn {
  width: 100%;
  height: 54px !important;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.18em;
  margin-top: 8px;
}

.login-hint {
  text-align: center;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--line-soft);
}
</style>
