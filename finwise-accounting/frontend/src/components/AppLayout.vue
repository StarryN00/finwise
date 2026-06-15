<script setup>
import { Lock, Plus, SwitchButton } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import { clearAuthSession, getAuthUser, isAuthenticated } from '../auth/session'
import { useWorkspaceStore } from '../stores/workspace'

const route = useRoute()
const router = useRouter()
const workspace = useWorkspaceStore()
const navItems = [
  { label: '工作台', path: '/' },
  { label: '企业名册', path: '/enterprises' },
  { label: '月度工作包', path: '/monthly-workspace' },
  { label: '账目明细', path: '/account-details' },
  { label: '资金流水', path: '/bank-ledger' },
  { label: '发票台账', path: '/invoice-ledger' },
  { label: '科目设置', path: '/account-subjects' },
  { label: '历史账套导入', path: '/historical-import' },
  { label: '凭证生成', path: '/vouchers' },
  { label: '凭证管理', path: '/voucher-management' },
  { label: '账簿', path: '/ledgers' },
  { label: '输出中心', path: '/output-center' },
  { label: '规则设置', path: '/rules' },
]

const isActive = computed(() => (item) => item.path === route.path)
const createDialogVisible = ref(false)
const isSubmitting = ref(false)
const passwordDialogVisible = ref(false)
const isPasswordSubmitting = ref(false)
const passwordFormRef = ref()
const now = new Date()
const yearOptions = computed(() => {
  const currentYear = now.getFullYear()
  return Array.from({ length: 8 }, (_, index) => currentYear - 3 + index)
})
const monthOptions = Array.from({ length: 12 }, (_, index) => index + 1)
const showLogout = computed(() => isAuthenticated())
const currentUser = computed(() => getAuthUser() || 'operator')
const packageForm = reactive({
  enterpriseId: '',
  periodYear: now.getFullYear(),
  periodMonth: now.getMonth() + 1,
})
const passwordForm = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})
const passwordRules = {
  oldPassword: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '新密码至少需要 8 位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== passwordForm.newPassword) {
          callback(new Error('两次输入的新密码不一致'))
          return
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
}

watch(
  () => workspace.enterprises,
  (enterprises) => {
    if (!packageForm.enterpriseId && enterprises.length) {
      packageForm.enterpriseId = enterprises[0].id
    }
  },
  { immediate: true },
)

async function createPackage() {
  if (!packageForm.enterpriseId) {
    ElMessage.warning('请先选择企业')
    return
  }
  isSubmitting.value = true
  try {
    await workspace.createMonthlyPackage(packageForm.enterpriseId, packageForm.periodYear, packageForm.periodMonth)
    createDialogVisible.value = false
    ElMessage.success('月度工作包已创建')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '创建工作包失败')
  } finally {
    isSubmitting.value = false
  }
}

function logout() {
  clearAuthSession()
  router.replace('/login')
}

function openPasswordDialog() {
  passwordForm.oldPassword = ''
  passwordForm.newPassword = ''
  passwordForm.confirmPassword = ''
  passwordDialogVisible.value = true
}

async function submitPasswordChange() {
  if (!passwordFormRef.value) return
  const isValid = await passwordFormRef.value.validate().catch(() => false)
  if (!isValid) return

  isPasswordSubmitting.value = true
  try {
    await api.auth.changePassword({
      old_password: passwordForm.oldPassword,
      new_password: passwordForm.newPassword,
    })
    passwordDialogVisible.value = false
    clearAuthSession()
    ElMessage.success('密码已修改，请使用新密码重新登录')
    router.replace('/login')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '修改密码失败')
  } finally {
    isPasswordSubmitting.value = false
  }
}
</script>

<template>
  <div class="app-shell">
    <aside class="app-sidebar">
      <div class="brand-lockup">
        <div class="brand-mark">智</div>
        <div>
          <strong>智税管家</strong>
          <span>代账月度工作台</span>
        </div>
      </div>
      <nav class="app-nav" aria-label="主导航">
        <router-link
          v-for="item in navItems"
          :key="item.label"
          :to="item.path"
          class="app-nav__item"
          :class="{ active: isActive(item) }"
        >
          <span class="app-nav__dot" />
          <span>{{ item.label }}</span>
        </router-link>
      </nav>
    </aside>

    <div class="app-main">
      <header class="app-topbar">
        <div>
          <p class="caption">苏州代账公司 · Phase 1</p>
          <h1 class="page-title">月度记账与申报工作台</h1>
        </div>
        <div class="topbar-actions">
          <span v-if="showLogout" class="current-user">当前用户：{{ currentUser }}</span>
          <el-button v-if="showLogout" :icon="Lock" plain @click="openPasswordDialog">修改密码</el-button>
          <el-button v-if="showLogout" :icon="SwitchButton" plain @click="logout">退出登录</el-button>
          <el-button type="primary" :icon="Plus" @click="createDialogVisible = true">创建本月工作包</el-button>
        </div>
      </header>
      <main class="app-content">
        <slot />
      </main>
    </div>
    <el-dialog v-model="createDialogVisible" title="创建月度工作包" width="420px">
      <el-form label-width="92px">
        <el-form-item label="企业">
          <el-select v-model="packageForm.enterpriseId" placeholder="选择企业" filterable>
            <el-option
              v-for="enterprise in workspace.enterprises"
              :key="enterprise.id"
              :label="enterprise.name"
              :value="enterprise.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="会计期间">
          <div class="period-row">
            <el-select v-model="packageForm.periodYear" placeholder="选择年份">
              <el-option v-for="year in yearOptions" :key="year" :label="`${year}年`" :value="year" />
            </el-select>
            <el-select v-model="packageForm.periodMonth" placeholder="选择月份">
              <el-option
                v-for="month in monthOptions"
                :key="month"
                :label="`${String(month).padStart(2, '0')}月`"
                :value="month"
              />
            </el-select>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="isSubmitting" @click="createPackage">创建</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="passwordDialogVisible" title="修改登录密码" width="420px">
      <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-width="92px">
        <el-form-item label="当前密码" prop="oldPassword">
          <el-input v-model="passwordForm.oldPassword" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item label="新密码" prop="newPassword">
          <el-input v-model="passwordForm.newPassword" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input v-model="passwordForm.confirmPassword" type="password" show-password autocomplete="new-password" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="isPasswordSubmitting" @click="submitPasswordChange">确认修改</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  min-height: 100vh;
}

.app-sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  padding: 20px 14px;
  overflow-y: auto;
  color: #d9e7fb;
  background: #0f1d32;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
}

.brand-lockup {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 6px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: var(--fw-radius-sm);
  color: var(--fw-brand-dark);
  background: #ffffff;
  font-weight: 800;
}

.brand-lockup strong {
  display: block;
  font-size: 16px;
  line-height: 1.2;
}

.brand-lockup span {
  display: block;
  margin-top: 2px;
  color: #9bb1ce;
  font-size: 12px;
}

.app-nav {
  display: grid;
  gap: 4px;
  margin-top: 18px;
}

.app-nav__item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 38px;
  padding: 8px 10px;
  border-radius: var(--fw-radius-sm);
  color: #b9cae2;
  font-size: 13px;
}

.app-nav__item:hover,
.app-nav__item.active {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.08);
}

.app-nav__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #5b74a0;
}

.app-nav__item.active .app-nav__dot {
  background: var(--fw-brand);
}

.app-main {
  min-width: 0;
  overflow: hidden;
}

.app-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  min-height: 82px;
  padding: 18px 28px;
  background: var(--fw-surface);
  border-bottom: 1px solid var(--fw-line);
}

.app-topbar .caption {
  margin: 0 0 4px;
}

.topbar-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.current-user {
  color: var(--fw-muted);
  font-size: 12px;
}

.period-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  width: 100%;
}

.app-content {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 18px;
  min-width: 0;
  overflow: hidden;
  padding: 24px 28px 40px;
}

@media (max-width: 860px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .app-sidebar {
    position: static;
    height: auto;
  }

  .app-topbar {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
