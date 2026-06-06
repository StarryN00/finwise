<template>
  <section class="subjects-page">
    <div class="subjects-panel">
      <div class="subjects-header">
        <div>
          <h2 class="section-title">科目设置</h2>
          <p class="caption">按企业维护会计科目启用状态与凭证可用范围</p>
        </div>
        <div class="subjects-actions">
          <el-select
            v-model="selectedEnterpriseId"
            placeholder="选择企业"
            filterable
            class="enterprise-select"
            @change="loadSubjects"
          >
            <el-option
              v-for="enterprise in workspace.enterprises"
              :key="enterprise.id"
              :label="enterprise.name"
              :value="enterprise.id"
            />
          </el-select>
          <el-button
            type="primary"
            :loading="isInitializing"
            :disabled="!selectedEnterpriseId"
            @click="initializeSubjects"
          >
            初始化科目
          </el-button>
        </div>
      </div>

      <div class="subjects-table-scroll">
        <el-table v-loading="isLoading" :data="subjects" class="subjects-table" stripe>
          <el-table-column prop="code" label="科目编码" min-width="110" />
          <el-table-column prop="name" label="科目名称" min-width="150" show-overflow-tooltip />
          <el-table-column label="类别" min-width="110">
            <template #default="{ row }">{{ categoryLabel(row.category) }}</template>
          </el-table-column>
          <el-table-column label="余额方向" min-width="100">
            <template #default="{ row }">{{ balanceDirectionLabel(row.normal_balance) }}</template>
          </el-table-column>
          <el-table-column label="末级" min-width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_leaf ? 'success' : 'info'" size="small">{{ booleanLabel(row.is_leaf) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="允许凭证" min-width="100">
            <template #default="{ row }">
              <el-tag :type="row.allow_voucher ? 'success' : 'info'" size="small">{{ booleanLabel(row.allow_voucher) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="启用" min-width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_enabled ? 'success' : 'danger'" size="small">{{ booleanLabel(row.is_enabled) }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { ref, watch } from 'vue'
import { api } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const selectedEnterpriseId = ref('')
const subjects = ref([])
const isLoading = ref(false)
const isInitializing = ref(false)
let subjectLoadRequestId = 0

watch(
  () => workspace.enterprises,
  (enterprises) => {
    if (!selectedEnterpriseId.value && enterprises.length) {
      selectedEnterpriseId.value = enterprises[0].id
      loadSubjects(enterprises[0].id)
    }
  },
  { immediate: true },
)

async function loadSubjects(enterpriseId = selectedEnterpriseId.value) {
  if (!enterpriseId) {
    subjectLoadRequestId += 1
    subjects.value = []
    return
  }
  const requestId = ++subjectLoadRequestId
  subjects.value = []
  isLoading.value = true
  try {
    const response = await api.accountSubjects.list(enterpriseId)
    if (isStaleSubjectLoad(requestId, enterpriseId)) return
    subjects.value = response.data
  } catch (error) {
    if (isStaleSubjectLoad(requestId, enterpriseId)) return
    subjects.value = []
    ElMessage.error(error?.response?.data?.detail || error?.message || '科目加载失败')
  } finally {
    if (!isStaleSubjectLoad(requestId, enterpriseId)) {
      isLoading.value = false
    }
  }
}

async function initializeSubjects() {
  const enterpriseId = selectedEnterpriseId.value
  if (!enterpriseId) {
    ElMessage.warning('请先选择企业')
    return
  }
  isInitializing.value = true
  try {
    await api.accountSubjects.initialize(enterpriseId)
    if (enterpriseId !== selectedEnterpriseId.value) return
    await loadSubjects(enterpriseId)
    if (enterpriseId !== selectedEnterpriseId.value) return
    ElMessage.success('科目已初始化')
  } catch (error) {
    if (enterpriseId !== selectedEnterpriseId.value) return
    ElMessage.error(error?.response?.data?.detail || error?.message || '科目初始化失败')
  } finally {
    isInitializing.value = false
  }
}

function isStaleSubjectLoad(requestId, enterpriseId) {
  return requestId !== subjectLoadRequestId || enterpriseId !== selectedEnterpriseId.value
}

function booleanLabel(value) {
  return value ? '是' : '否'
}

function categoryLabel(value) {
  const labels = {
    ASSET: '资产',
    LIABILITY: '负债',
    EQUITY: '所有者权益',
    COST: '成本',
    REVENUE: '收入',
    EXPENSE: '费用',
    PROFIT_LOSS: '损益',
  }
  return labels[value] || value || '-'
}

function balanceDirectionLabel(value) {
  const labels = {
    DEBIT: '借方',
    CREDIT: '贷方',
  }
  return labels[value] || value || '-'
}
</script>

<style scoped>
.subjects-page {
  display: grid;
  gap: 16px;
}

.subjects-panel {
  padding: 16px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.subjects-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.subjects-header .caption {
  margin: 4px 0 0;
}

.subjects-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.enterprise-select {
  width: 260px;
}

.subjects-table-scroll {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  border-top: 1px solid var(--fw-line);
  scrollbar-color: var(--fw-brand) #eaf2ff;
  scrollbar-width: thin;
}

.subjects-table-scroll::-webkit-scrollbar {
  height: 12px;
}

.subjects-table-scroll::-webkit-scrollbar-track {
  background: #eaf2ff;
}

.subjects-table-scroll::-webkit-scrollbar-thumb {
  border: 2px solid #eaf2ff;
  border-radius: 999px;
  background: var(--fw-brand);
}

.subjects-table {
  width: 100%;
  min-width: 750px;
}

.subjects-table :deep(.el-table__inner-wrapper) {
  width: 100%;
}

@media (max-width: 760px) {
  .subjects-header,
  .subjects-actions {
    display: grid;
  }

  .enterprise-select {
    width: 100%;
  }
}
</style>
