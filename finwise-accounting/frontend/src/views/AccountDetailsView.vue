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
        <el-button :loading="isAiMatching" @click="runAiMatching">AI 智能匹配</el-button>
        <el-button type="primary" @click="runMatching">运行匹配</el-button>
      </div>
    </div>
    <el-table v-loading="workspace.isLoading" :data="rows" stripe>
      <el-table-column prop="sourceCompleteness" label="统一视图" width="120" />
      <el-table-column prop="date" label="日期" width="120" />
      <el-table-column prop="summary" label="摘要" min-width="180" show-overflow-tooltip />
      <el-table-column prop="remark" label="备注" min-width="180" show-overflow-tooltip />
      <el-table-column prop="payer" label="付款方" min-width="160" show-overflow-tooltip />
      <el-table-column prop="payee" label="收款方" min-width="160" show-overflow-tooltip />
      <el-table-column prop="seller" label="销售方" min-width="160" show-overflow-tooltip />
      <el-table-column prop="buyer" label="购买方" min-width="160" show-overflow-tooltip />
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
import { computed, ref } from 'vue'
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
  try {
    await workspace.runMatching(activePackage.id)
    ElMessage.success('匹配已完成，列表已刷新')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '运行匹配失败')
  }
}

async function runAiMatching() {
  const activePackage = workspace.activePackage
  if (!activePackage) {
    ElMessage.warning('请先创建月度工作包')
    return
  }
  isAiMatching.value = true
  try {
    const result = await workspace.runAiMatching(activePackage.id)
    ElMessage.success(`AI 已生成 ${result?.created_matches ?? 0} 条待确认匹配`)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || 'AI 匹配失败')
  } finally {
    isAiMatching.value = false
  }
}

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
  gap: 8px;
}

@media (max-width: 900px) {
  .account-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
