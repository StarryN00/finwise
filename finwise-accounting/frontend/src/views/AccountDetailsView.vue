<template>
  <DataTableShell title="账目明细" description="流水、发票与待确认事项的统一工作表" action-label="运行匹配">
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
          <el-button size="small" :disabled="row.status === 'CONFIRMED'">确认</el-button>
        </template>
      </el-table-column>
    </el-table>
  </DataTableShell>
</template>

<script setup>
import { computed, ref } from 'vue'
import DataTableShell from '../components/DataTableShell.vue'
import StatusTag from '../components/StatusTag.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const activeTab = ref('bank')

const rows = computed(() => {
  if (activeTab.value === 'pending') {
    return workspace.accountRows.filter((row) => row.status !== 'CONFIRMED')
  }
  if (activeTab.value === 'invoice') {
    return workspace.accountRows.filter((row) => row.type === '发票')
  }
  return workspace.accountRows.filter((row) => row.type === '流水')
})
</script>

<style scoped>
.account-tabs {
  padding: 0 16px;
}
</style>
