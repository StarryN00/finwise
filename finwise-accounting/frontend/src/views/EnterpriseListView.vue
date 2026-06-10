<template>
  <DataTableShell
    title="企业名册"
    description="苏州客户的月度资料、确认和报告状态"
    action-label="新增企业"
    @action="router.push('/enterprises/init')"
  >
    <template #filters>
      <el-button type="primary" plain :loading="isCreatingScanJob" @click="createTechnologyScanJob">批量扫描科技画像</el-button>
      <el-button plain @click="openScanJobDrawer">查看扫描任务</el-button>
      <el-input v-model="keyword" placeholder="搜索企业" clearable style="width: 220px" />
    </template>
    <el-table
      v-loading="workspace.isLoading"
      :data="filteredEnterprises"
      stripe
      @selection-change="selectedEnterprises = $event"
      @row-click="openEnterpriseDetail"
    >
      <el-table-column type="selection" width="44" />
      <el-table-column label="企业名称" min-width="220">
        <template #default="{ row }">
          <el-button class="enterprise-name-link" link type="primary" @click.stop="openEnterpriseDetail(row)">
            {{ row.name }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column prop="taxpayerType" label="纳税人类型" width="140" />
      <el-table-column label="科技画像" min-width="220">
        <template #default="{ row }">
          <div class="technology-cell">
            <el-tag size="small" :type="formatTechnologyStatus(row.technologyProfileStatus).type" effect="light">
              {{ formatTechnologyStatus(row.technologyProfileStatus).label }}
            </el-tag>
            <span v-if="row.technologyTags?.length" class="technology-tags">{{ row.technologyTags.join('、') }}</span>
            <span v-else class="technology-empty">{{ row.ipSummary && row.ipSummary !== '-' ? row.ipSummary : '待扫描' }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="latestMonth" label="最新月份" width="120" />
      <el-table-column label="资料状态" width="130">
        <template #default="{ row }">
          <StatusTag :status="row.dataStatus" />
        </template>
      </el-table-column>
      <el-table-column prop="pendingConfirmations" label="待确认" width="110" align="right" />
      <el-table-column label="报告状态" width="130">
        <template #default="{ row }">
          <StatusTag :status="row.reportStatus" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button
            link
            type="danger"
            :loading="deletingEnterpriseId === row.id"
            @click.stop="confirmDeleteEnterprise(row)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="scanJobDrawerVisible" title="科技画像扫描任务" size="520px" @open="loadTechnologyScanJobs">
      <div class="scan-job-drawer">
        <div class="scan-job-summary">
          <strong>{{ selectedScanJob ? formatScanJobStatus(selectedScanJob.status) : '暂无任务' }}</strong>
          <span v-if="selectedScanJob">
            共 {{ selectedScanJob.target_enterprise_count }} 家，已完成 {{ selectedScanJob.completed_enterprise_count }} 家，
            需处理 {{ selectedScanJob.review_required_count }} 家，失败 {{ selectedScanJob.failed_enterprise_count }} 家
          </span>
        </div>
        <el-table :data="technologyScanJobs" stripe empty-text="暂无扫描任务" @row-click="selectScanJob">
          <el-table-column prop="provider" label="来源" width="100" />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">{{ formatScanJobStatus(row.status) }}</template>
          </el-table-column>
          <el-table-column prop="target_enterprise_count" label="企业数" width="90" align="right" />
          <el-table-column prop="created_at" label="创建时间" min-width="150">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
        <el-divider />
        <el-table :data="selectedScanJob?.items || []" stripe empty-text="请选择任务查看企业明细">
          <el-table-column prop="enterprise_name" label="企业" min-width="180" show-overflow-tooltip />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">{{ formatScanItemStatus(row.status) }}</template>
          </el-table-column>
          <el-table-column label="原因" min-width="140">
            <template #default="{ row }">{{ formatFailureReason(row.failure_reason) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button link type="primary" @click.stop="router.push(`/enterprises/${row.enterprise_id}`)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-drawer>
  </DataTableShell>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api/client'
import DataTableShell from '../components/DataTableShell.vue'
import StatusTag from '../components/StatusTag.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const router = useRouter()
const keyword = ref('')
const selectedEnterprises = ref([])
const scanJobDrawerVisible = ref(false)
const technologyScanJobs = ref([])
const selectedScanJob = ref(null)
const isCreatingScanJob = ref(false)
const deletingEnterpriseId = ref('')

const filteredEnterprises = computed(() => {
  const value = keyword.value.trim()
  if (!value) return workspace.enterprises
  return workspace.enterprises.filter((enterprise) => enterprise.name.includes(value))
})

function openEnterpriseDetail(row) {
  router.push(`/enterprises/${row.id}`)
}

async function createTechnologyScanJob() {
  isCreatingScanJob.value = true
  try {
    const selectedIds = selectedEnterprises.value.map((enterprise) => enterprise.id)
    const payload = selectedIds.length
      ? { provider: 'QICHACHA', scope_type: 'SELECTED', enterprise_ids: selectedIds }
      : { provider: 'QICHACHA', scope_type: 'UNSCANNED' }
    const response = await api.technologyScanJobs.create(payload)
    selectedScanJob.value = response.data
    scanJobDrawerVisible.value = true
    await loadTechnologyScanJobs()
    ElMessage.success('科技画像扫描任务已创建')
  } finally {
    isCreatingScanJob.value = false
  }
}

async function confirmDeleteEnterprise(row) {
  const enterpriseId = row?.id
  if (!enterpriseId) return
  try {
    await ElMessageBox.confirm(
      `删除后将同时删除“${row.name}”的期初数据、月度工作包、导入记录、银行流水、发票、匹配记录、凭证、账簿、报表、规则和科技画像等所有关联数据，且不可恢复。请确认是否继续？`,
      '确认删除企业',
      {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return
  }
  deletingEnterpriseId.value = enterpriseId
  try {
    await api.enterprises.remove(enterpriseId)
    selectedEnterprises.value = selectedEnterprises.value.filter((enterprise) => enterprise.id !== enterpriseId)
    const activeEnterpriseId = workspace.activePackage?.enterpriseId || workspace.activePackage?.enterprise_id
    if (workspace.selectedPackageId && activeEnterpriseId === enterpriseId) {
      workspace.selectedPackageId = ''
    }
    await workspace.loadWorkspace()
    ElMessage.success('企业及关联数据已删除')
  } catch (error) {
    ElMessage.error(formatEnterpriseDeleteError(error))
  } finally {
    deletingEnterpriseId.value = ''
  }
}

async function openScanJobDrawer() {
  scanJobDrawerVisible.value = true
  await loadTechnologyScanJobs()
}

async function loadTechnologyScanJobs() {
  const response = await api.technologyScanJobs.list()
  technologyScanJobs.value = response.data.jobs
  if (!selectedScanJob.value && technologyScanJobs.value.length) {
    selectedScanJob.value = technologyScanJobs.value[0]
  } else if (selectedScanJob.value) {
    selectedScanJob.value = technologyScanJobs.value.find((job) => job.id === selectedScanJob.value.id) || selectedScanJob.value
  }
}

function selectScanJob(row) {
  selectedScanJob.value = row
}

function formatTechnologyStatus(status) {
  const statusMap = {
    NOT_SCANNED: { label: '未扫描', type: 'info' },
    SCANNED_PENDING_REVIEW: { label: '待确认', type: 'warning' },
    CONFIRMED: { label: '已确认', type: 'success' },
    NEEDS_RESCAN: { label: '需复查', type: 'danger' },
    FAILED: { label: '扫描失败', type: 'danger' },
  }
  return statusMap[status] || { label: status || '未扫描', type: 'info' }
}

function formatScanJobStatus(status) {
  const statusMap = {
    PENDING: '待运行',
    RUNNING: '运行中',
    COMPLETED: '已完成',
    PARTIAL_FAILED: '部分需处理',
    FAILED: '失败',
    PAUSED: '已暂停',
  }
  return statusMap[status] || status || '-'
}

function formatScanItemStatus(status) {
  const statusMap = {
    PENDING: '待扫描',
    RUNNING: '扫描中',
    COMPLETED: '已完成',
    NEEDS_REVIEW: '需人工处理',
    FAILED: '失败',
    SKIPPED: '已跳过',
  }
  return statusMap[status] || status || '-'
}

function formatFailureReason(reason) {
  const reasonMap = {
    LOGIN_REQUIRED: '需登录',
    CAPTCHA_REQUIRED: '需验证码',
    AMBIGUOUS_MATCH: '主体不确定',
    NOT_FOUND: '未找到',
    NO_INNOVATION_PANEL: '未找到科创分',
    PAGE_STRUCTURE_CHANGED: '页面结构变化',
    PROVIDER_RATE_LIMITED: '平台限流',
    UNKNOWN_ERROR: '未知错误',
  }
  return reasonMap[reason] || reason || '-'
}

function formatDateTime(value) {
  if (!value) return '-'
  return String(value).slice(0, 16).replace('T', ' ')
}

function formatEnterpriseDeleteError(error) {
  const detail = error?.response?.data?.detail
  if (detail) return `企业删除失败：${detail}`
  if (error?.response?.status === 404) return '企业删除失败：删除接口不可用或企业不存在，请刷新后重试'
  if (error?.message) return `企业删除失败：${error.message}`
  return '企业删除失败，请刷新后重试'
}
</script>

<style scoped>
.enterprise-name-link {
  padding: 0;
  font-weight: 700;
}

.technology-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.technology-tags,
.technology-empty {
  min-width: 0;
  overflow: hidden;
  color: var(--fw-ink-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scan-job-drawer {
  display: grid;
  gap: 14px;
}

.scan-job-summary {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-bg);
}

.scan-job-summary span {
  color: var(--fw-ink-muted);
  font-size: 13px;
}
</style>
