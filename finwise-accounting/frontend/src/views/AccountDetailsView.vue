<template>
  <PackageContextBar
    aria-label="当前操作主体"
    status-label="待确认事项"
    :status-value="`${workspace.activePackage?.pending ?? 0} 项`"
  />
  <DataTableShell
    title="账目明细"
    description="流水、发票与待确认事项的统一工作表"
  >
    <div class="account-toolbar">
      <el-segmented v-model="activeFilter" :options="filterOptions" />
      <div class="account-toolbar__actions">
        <el-button :loading="isAiMatching" :disabled="isRuleMatching" @click="runAiMatching">AI 智能匹配</el-button>
        <el-button type="primary" :loading="isRuleMatching" :disabled="isAiMatching" @click="runMatching">运行匹配</el-button>
      </div>
    </div>
    <p class="match-hint">可先运行匹配使用确定性规则快速处理，再用 AI 智能匹配补充复杂或模糊场景；两者没有强制顺序。</p>
    <div v-if="isAiMatching" class="ai-progress-panel">
      <div>
        <strong>AI 正在分析流水与发票</strong>
        <span>通常需要几十秒，完成后会自动刷新待确认匹配。</span>
      </div>
      <el-progress :percentage="aiProgress" :stroke-width="10" striped striped-flow />
    </div>
    <div class="scroll-affordance">
      <span>表格可左右滑动查看更多字段</span>
    </div>
    <div class="account-table-scroll">
      <el-table v-loading="workspace.isLoading" :data="rows" class="compact-account-table" stripe>
        <el-table-column prop="sourceCompleteness" label="完整性" width="116" />
        <el-table-column prop="date" label="日期" width="112" />
        <el-table-column prop="directionType" label="类型" width="88" />
        <el-table-column prop="transactionCounterparty" label="交易对方" min-width="150" show-overflow-tooltip />
        <el-table-column prop="invoiceCounterparty" label="发票对方" min-width="150" show-overflow-tooltip />
        <el-table-column prop="remark" label="摘要/备注" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="130">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column prop="confidence" label="置信度" width="100" align="right" />
        <el-table-column prop="businessType" label="业务类型" width="140" />
        <el-table-column prop="amount" label="金额" width="130" align="right" />
        <el-table-column prop="tax" label="税额" width="120" align="right" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button
              size="small"
              :disabled="row.status === 'CONFIRMED' || !row.confirmType"
              @click="startConfirm(row)"
            >
              确认
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </DataTableShell>
  <el-dialog v-model="confirmDialogVisible" title="确认待处理事项" width="440px">
    <el-form label-width="96px">
      <el-form-item label="摘要">
        <span>{{ currentRow?.summary }}</span>
      </el-form-item>
      <el-form-item label="业务类型">
        <el-input v-model="confirmForm.businessType" placeholder="例如：BANK_FEE / CONSULTING_SERVICE" />
      </el-form-item>
      <el-form-item v-if="canSaveRule" label="规则沉淀">
        <el-checkbox v-model="confirmForm.saveAsRule">保存为该企业的匹配规则</el-checkbox>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="confirmDialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="isConfirming" @click="confirmCurrentRow">确认</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import DataTableShell from '../components/DataTableShell.vue'
import PackageContextBar from '../components/PackageContextBar.vue'
import StatusTag from '../components/StatusTag.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const activeFilter = ref('all')
const confirmDialogVisible = ref(false)
const isConfirming = ref(false)
const isAiMatching = ref(false)
const isRuleMatching = ref(false)
const aiProgress = ref(0)
let aiProgressTimer = null
const currentRow = ref(null)
const confirmForm = ref({
  businessType: '',
  saveAsRule: false,
})

const canSaveRule = computed(() => currentRow.value?.sourceType === 'BANK_TRANSACTION')
const filterOptions = [
  { label: '全部', value: 'all' },
  { label: '待确认', value: 'pending' },
  { label: '缺失发票', value: 'missingInvoice' },
  { label: '缺失转账', value: 'missingBank' },
  { label: '已完整', value: 'complete' },
]

const rows = computed(() => {
  if (activeFilter.value === 'pending') {
    return workspace.accountRows.filter((row) => row.status !== 'CONFIRMED')
  }
  if (activeFilter.value === 'missingInvoice') {
    return workspace.accountRows.filter((row) => row.sourceCompleteness === '缺失发票主体')
  }
  if (activeFilter.value === 'missingBank') {
    return workspace.accountRows.filter((row) => row.sourceCompleteness === '缺失转账主体')
  }
  if (activeFilter.value === 'complete') {
    return workspace.accountRows.filter((row) => row.sourceCompleteness === '流水+发票')
  }
  return workspace.accountRows
})

async function runMatching() {
  const activePackage = workspace.activePackage
  if (!activePackage) {
    ElMessage.warning('请先创建月度工作包')
    return
  }
  isRuleMatching.value = true
  try {
    await workspace.runMatching(activePackage.id)
    ElMessage.success('匹配已完成，列表已刷新')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '运行匹配失败')
  } finally {
    isRuleMatching.value = false
  }
}

async function runAiMatching() {
  const activePackage = workspace.activePackage
  if (!activePackage) {
    ElMessage.warning('请先创建月度工作包')
    return
  }
  isAiMatching.value = true
  startAiProgress()
  try {
    const result = await workspace.runAiMatching(activePackage.id)
    aiProgress.value = 100
    if (result?.aiStatus === 'FALLBACK') {
      ElMessage.warning(`${result.message || 'AI 响应较慢，已用本地候选规则生成待确认建议'}（${result?.created_matches ?? 0} 条）`)
      return
    }
    if (result?.aiStatus === 'UNAVAILABLE') {
      ElMessage.warning(result.message || 'AI 服务暂时不可用，请稍后重试')
      return
    }
    ElMessage.success(`AI 已生成 ${result?.created_matches ?? 0} 条待确认匹配`)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || 'AI 匹配失败')
  } finally {
    stopAiProgress()
    isAiMatching.value = false
  }
}

function startAiProgress() {
  stopAiProgress()
  aiProgress.value = 8
  aiProgressTimer = window.setInterval(() => {
    if (aiProgress.value < 88) {
      aiProgress.value += 4
    } else if (aiProgress.value < 96) {
      aiProgress.value += 1
    }
  }, 1200)
}

function stopAiProgress() {
  if (aiProgressTimer) {
    window.clearInterval(aiProgressTimer)
    aiProgressTimer = null
  }
}

onBeforeUnmount(() => {
  stopAiProgress()
})

async function startConfirm(row) {
  if (row.confirmType === 'match') {
    await confirmRow(row, {})
    return
  }
  currentRow.value = row
  confirmForm.value = {
    businessType: row.businessType && row.businessType !== '待确认' ? row.businessType : defaultBusinessType(row),
    saveAsRule: row.confirmType === 'unmatched' && row.sourceType === 'BANK_TRANSACTION',
  }
  confirmDialogVisible.value = true
}

async function confirmCurrentRow() {
  if (!currentRow.value) return
  if (!confirmForm.value.businessType.trim()) {
    ElMessage.warning('请填写业务类型')
    return
  }
  await confirmRow(currentRow.value, {
    businessType: confirmForm.value.businessType,
    saveAsRule: confirmForm.value.saveAsRule,
  })
  confirmDialogVisible.value = false
}

async function confirmRow(row, payload) {
  isConfirming.value = true
  try {
    await workspace.confirmRow(row, payload)
    ElMessage.success('已确认')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '确认失败')
  } finally {
    isConfirming.value = false
  }
}

function defaultBusinessType(row) {
  if (row.type === '发票') return row.sourceType === 'INVOICE' ? 'INVOICE_CONFIRMED' : 'OUTPUT_REVENUE'
  const amount = String(row.amount || '')
  return amount.includes('-') ? 'OTHER_INCOME' : 'OTHER_EXPENSE'
}
</script>

<style scoped>
.account-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 16px 12px;
}

.account-toolbar__actions {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 8px;
}

.match-hint {
  margin: 0;
  padding: 0 16px 12px;
  color: var(--fw-text-muted);
  font-size: 12px;
}

.ai-progress-panel {
  display: grid;
  grid-template-columns: minmax(220px, 0.8fr) minmax(260px, 1fr);
  gap: 16px;
  align-items: center;
  margin: 0 16px 12px;
  padding: 12px;
  border: 1px solid #bfdbfe;
  border-radius: var(--fw-radius-sm);
  background: #eff6ff;
}

.ai-progress-panel strong,
.ai-progress-panel span {
  display: block;
}

.ai-progress-panel span {
  margin-top: 4px;
  color: var(--fw-text-muted);
  font-size: 12px;
}

.scroll-affordance {
  position: sticky;
  bottom: 0;
  z-index: 2;
  display: flex;
  justify-content: flex-end;
  padding: 0 16px 8px;
  color: var(--fw-brand);
  font-size: 12px;
}

.scroll-affordance span {
  padding: 4px 10px;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  background: #eff6ff;
}

.account-table-scroll {
  max-height: calc(100vh - 360px);
  max-width: 100%;
  overflow-x: auto;
  overflow-y: auto;
  border-top: 1px solid var(--fw-line);
  scrollbar-color: var(--fw-brand) #eaf2ff;
  scrollbar-width: thin;
}

.account-table-scroll::-webkit-scrollbar {
  height: 12px;
}

.account-table-scroll::-webkit-scrollbar-track {
  background: #eaf2ff;
}

.account-table-scroll::-webkit-scrollbar-thumb {
  border: 2px solid #eaf2ff;
  border-radius: 999px;
  background: var(--fw-brand);
}

.compact-account-table {
  min-width: 1120px;
}

@media (max-width: 900px) {
  .account-toolbar {
    align-items: center;
    overflow-x: auto;
  }

  .ai-progress-panel {
    grid-template-columns: 1fr;
  }
}
</style>
