<script setup>
import { Lock, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import { setAuthSession } from '../auth/session'

const route = useRoute()
const router = useRouter()
const isLoading = ref(false)
const form = reactive({
  username: '',
  password: '',
})

onMounted(async () => {
  try {
    const response = await api.auth.status()
    if (!response.data?.enabled) {
      router.replace('/')
    }
  } catch {
    ElMessage.error('无法连接登录服务')
  }
})

async function login() {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning('请输入账号和密码')
    return
  }

  isLoading.value = true
  try {
    const response = await api.auth.login({
      username: form.username.trim(),
      password: form.password,
    })
    setAuthSession(response.data.access_token, response.data.username)
    ElMessage.success('登录成功')
    router.replace(typeof route.query.redirect === 'string' ? route.query.redirect : '/')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '账号或密码错误')
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="brand-row">
        <div class="brand-mark">智</div>
        <div>
          <p>智税管家</p>
          <span>生产环境访问验证</span>
        </div>
      </div>

      <div class="login-copy">
        <h1>登录工作台</h1>
        <p>请输入管理员账号后继续访问月度记账与申报系统。</p>
      </div>

      <el-form class="login-form" @submit.prevent>
        <el-form-item>
          <el-input
            v-model="form.username"
            :prefix-icon="User"
            autocomplete="username"
            placeholder="账号"
            size="large"
            @keyup.enter="login"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            :prefix-icon="Lock"
            autocomplete="current-password"
            placeholder="密码"
            show-password
            size="large"
            type="password"
            @keyup.enter="login"
          />
        </el-form-item>
        <el-button class="login-button" type="primary" size="large" :loading="isLoading" @click="login">
          登录
        </el-button>
      </el-form>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  display: grid;
  min-height: 100vh;
  place-items: center;
  padding: 32px;
  background:
    linear-gradient(135deg, rgba(15, 29, 50, 0.92), rgba(31, 63, 105, 0.86)),
    radial-gradient(circle at 74% 20%, rgba(57, 145, 255, 0.35), transparent 32%),
    #0f1d32;
}

.login-panel {
  width: min(420px, 100%);
  padding: 34px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 24px 80px rgba(6, 16, 30, 0.35);
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 8px;
  color: #ffffff;
  background: #1f7aff;
  font-weight: 800;
}

.brand-row p,
.login-copy h1,
.login-copy p {
  margin: 0;
}

.brand-row p {
  color: #122034;
  font-size: 17px;
  font-weight: 800;
}

.brand-row span {
  color: #667085;
  font-size: 12px;
}

.login-copy {
  margin: 30px 0 24px;
}

.login-copy h1 {
  color: #111827;
  font-size: 26px;
  line-height: 1.2;
}

.login-copy p {
  margin-top: 8px;
  color: #667085;
  font-size: 14px;
}

.login-form {
  display: grid;
  gap: 4px;
}

.login-button {
  width: 100%;
}
</style>
