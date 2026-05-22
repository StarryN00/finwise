<template>
  <section class="metric-grid">
    <MetricCard
      v-for="metric in workspace.metrics"
      :key="metric.label"
      :label="metric.label"
      :value="metric.value"
      :subtext="metric.subtext"
      :tone="metric.tone"
    />
  </section>
  <el-alert v-if="workspace.loadError" type="error" :title="workspace.loadError" show-icon />

  <DataTableShell title="月度工作包" description="按企业跟踪导入、匹配、申报与报告状态" action-label="导入资料">
    <template #filters>
      <el-select v-model="statusFilter" placeholder="状态" style="width: 148px">
        <el-option label="全部状态" value="ALL" />
        <el-option label="待确认" value="PENDING_CONFIRMATION" />
        <el-option label="可导出" value="READY_TO_EXPORT" />
        <el-option label="数据不足" value="DATA_INSUFFICIENT" />
      </el-select>
    </template>
    <el-table v-loading="workspace.isLoading" :data="filteredPackages" stripe>
      <el-table-column prop="company" label="企业名称" min-width="220" />
      <el-table-column prop="period" label="期间" width="110" />
      <el-table-column label="状态" width="130">
        <template #default="{ row }">
          <StatusTag :status="row.status" />
        </template>
      </el-table-column>
      <el-table-column prop="pending" label="待确认" width="110" align="right" />
      <el-table-column prop="tax" label="预计增值税" width="140" align="right">
        <template #default="{ row }">
          <span class="amount">{{ row.tax }}</span>
        </template>
      </el-table-column>
    </el-table>
  </DataTableShell>
</template>

<script setup>
import { computed, ref } from 'vue'
import DataTableShell from '../components/DataTableShell.vue'
import MetricCard from '../components/MetricCard.vue'
import StatusTag from '../components/StatusTag.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const statusFilter = ref('ALL')

const filteredPackages = computed(() => {
  if (statusFilter.value === 'ALL') {
    return workspace.workPackages
  }
  return workspace.workPackages.filter((item) => item.status === statusFilter.value)
})
</script>

<style scoped>
.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

@media (max-width: 960px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
