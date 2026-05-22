<template>
  <DataTableShell
    title="账目明细"
    description="流水、发票与待确认事项的统一工作表"
    action-label="运行匹配"
    @action="runMatching"
  >
    <el-tabs v-model="activeTab" class="account-tabs">
      <el-tab-pane label="流水视图" name="bank" />
      <el-tab-pane label="发票视图" name="invoice" />
      <el-tab-pane label="待确认清单" name="pending" />
    </el-tabs>
    <el-table v-loading="workspace.isLoading" :data="rows" stripe>
      <el-table-column prop="type" label="类型" width="90" />
      <el-table-column prop="date" label="日期" width="120" />
      <el-table-column prop="summary" label="摘要" min-width="180" />
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
import StatusTag from '../components/StatusTag.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const activeTab = ref('bank')
const confirmDialogVisible = ref(false)
const isConfirming = ref(false)
const currentRow = ref(null)
const confirmForm = ref({
  businessType: '',
  saveAsRule: false,
})

const canSaveRule = computed(() => currentRow.value?.sourceType === 'BANK_TRANSACTION')

const rows = computed(() => {
  if (activeTab.value === 'pending') {
    return workspace.accountRows.filter((row) => row.status !== 'CONFIRMED')
  }
  if (activeTab.value === 'invoice') {
    return workspace.accountRows.filter((row) => row.type === '发票')
  }
  return workspace.accountRows.filter((row) => row.type === '流水')
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
.account-tabs {
  padding: 0 16px;
}
</style>
