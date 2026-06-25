<template>
  <section class="package-context-bar">
    <div class="context-picker">
      <span class="context-label">当前操作主体</span>
      <el-select
        v-model="selectedEnterpriseId"
        class="context-select"
        filterable
        placeholder="选择企业主体"
        :loading="workspace.isLoading"
        @change="changeEnterprise"
      >
        <el-option
          v-for="item in enterpriseOptions"
          :key="item.enterpriseId"
          :label="item.company"
          :value="item.enterpriseId"
        />
      </el-select>
    </div>
    <div class="context-picker">
      <span class="context-label">工作期间</span>
      <el-select
        v-model="selectedPeriodPackageId"
        class="context-select"
        placeholder="选择工作期间"
        :disabled="!selectedEnterpriseId || !periodOptions.length"
        :loading="workspace.isLoading"
        @change="changePackage"
      >
        <el-option
          v-for="item in periodOptions"
          :key="item.id"
          :label="item.period"
          :value="item.id"
        />
      </el-select>
    </div>
    <div>
      <span class="context-label">{{ statusLabel }}</span>
      <strong>{{ statusValue }}</strong>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useWorkspaceStore } from '../stores/workspace'

const props = defineProps({
  statusLabel: {
    type: String,
    default: '当前状态',
  },
  statusValue: {
    type: String,
    default: '-',
  },
})

const workspace = useWorkspaceStore()
const selectedEnterpriseId = ref('')
const selectedPeriodPackageId = ref('')
const activePackage = computed(() => workspace.activePackage)
const statusLabel = computed(() => props.statusLabel)
const statusValue = computed(() => props.statusValue)
const enterpriseOptions = computed(() => {
  const seen = new Set()
  const options = []
  for (const item of workspace.enterprises) {
    if (!item.id || seen.has(item.id)) continue
    seen.add(item.id)
    options.push({ enterpriseId: item.id, company: item.name })
  }
  for (const item of workspace.workPackages) {
    if (!item.enterpriseId || seen.has(item.enterpriseId)) continue
    seen.add(item.enterpriseId)
    options.push({ enterpriseId: item.enterpriseId, company: item.company })
  }
  return options
})
const periodOptions = computed(() =>
  workspace.workPackages.filter((item) => item.enterpriseId === selectedEnterpriseId.value),
)

watch(
  [activePackage, enterpriseOptions],
  (value) => {
    const packageValue = value[0]
    const options = value[1]
    const hasSelectedEnterprise = options.some((item) => item.enterpriseId === selectedEnterpriseId.value)
    selectedEnterpriseId.value =
      packageValue?.enterpriseId || (hasSelectedEnterprise ? selectedEnterpriseId.value : options[0]?.enterpriseId || '')
    selectedPeriodPackageId.value = packageValue?.id || ''
  },
  { immediate: true },
)

async function changeEnterprise(enterpriseId) {
  if (!enterpriseId) return
  const currentPeriod = activePackage.value?.period
  const nextPackage =
    workspace.workPackages.find((item) => item.enterpriseId === enterpriseId && item.period === currentPeriod) ||
    workspace.workPackages.find((item) => item.enterpriseId === enterpriseId)
  if (!nextPackage || nextPackage.id === workspace.selectedPackageId) return
  await changePackage(nextPackage.id)
}

async function changePackage(packageId) {
  if (!packageId || packageId === workspace.selectedPackageId) return
  try {
    await workspace.selectPackage(packageId)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '切换企业失败')
  }
}
</script>

<style scoped>
.package-context-bar {
  display: grid;
  grid-template-columns: minmax(260px, 1.2fr) minmax(160px, 0.7fr) minmax(200px, 1fr);
  gap: 16px;
  align-items: end;
  padding: 16px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.context-label {
  display: block;
  margin-bottom: 6px;
  color: var(--fw-text-muted);
  font-size: 12px;
}

.package-context-bar strong {
  display: block;
  min-height: 32px;
  color: var(--fw-text);
  font-size: 16px;
  line-height: 32px;
}

.context-select {
  width: 100%;
}

@media (max-width: 900px) {
  .package-context-bar {
    grid-template-columns: 1fr;
  }
}
</style>
