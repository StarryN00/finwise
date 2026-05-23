<template>
  <DataTableShell
    title="企业名册"
    description="苏州客户的月度资料、确认和报告状态"
    action-label="新增企业"
    @action="router.push('/enterprises/init')"
  >
    <template #filters>
      <el-input v-model="keyword" placeholder="搜索企业" clearable style="width: 220px" />
    </template>
    <el-table v-loading="workspace.isLoading" :data="filteredEnterprises" stripe @row-click="openEnterpriseDetail">
      <el-table-column label="企业名称" min-width="220">
        <template #default="{ row }">
          <el-button class="enterprise-name-link" link type="primary" @click.stop="openEnterpriseDetail(row)">
            {{ row.name }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column prop="taxpayerType" label="纳税人类型" width="140" />
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
    </el-table>
  </DataTableShell>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import DataTableShell from '../components/DataTableShell.vue'
import StatusTag from '../components/StatusTag.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const router = useRouter()
const keyword = ref('')

const filteredEnterprises = computed(() => {
  const value = keyword.value.trim()
  if (!value) return workspace.enterprises
  return workspace.enterprises.filter((enterprise) => enterprise.name.includes(value))
})

function openEnterpriseDetail(row) {
  router.push(`/enterprises/${row.id}`)
}
</script>

<style scoped>
.enterprise-name-link {
  padding: 0;
  font-weight: 700;
}
</style>
