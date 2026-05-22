<template>
  <section class="package-context-bar">
    <div class="context-picker">
      <span class="context-label">当前操作主体</span>
      <el-select
        v-model="selectedPackageId"
        class="package-select"
        filterable
        placeholder="搜索企业或期间"
        :loading="workspace.isLoading"
        @change="changePackage"
      >
        <el-option
          v-for="item in workspace.workPackages"
          :key="item.id"
          :label="`${item.company} · ${item.period}`"
          :value="item.id"
        >
          <span class="option-title">{{ item.company }}</span>
          <span class="option-meta">{{ item.period }}</span>
        </el-option>
      </el-select>
    </div>
    <div>
      <span class="context-label">工作期间</span>
      <strong>{{ activePackage?.period || '-' }}</strong>
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
const selectedPackageId = ref('')
const activePackage = computed(() => workspace.activePackage)
const statusLabel = computed(() => props.statusLabel)
const statusValue = computed(() => props.statusValue)

watch(
  () => workspace.selectedPackageId,
  (value) => {
    selectedPackageId.value = value
  },
  { immediate: true },
)

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
  grid-template-columns: minmax(320px, 1.4fr) minmax(160px, 0.8fr) minmax(200px, 1fr);
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

.package-select {
  width: 100%;
}

.option-title {
  float: left;
}

.option-meta {
  float: right;
  margin-left: 20px;
  color: var(--fw-text-muted);
  font-size: 12px;
}

@media (max-width: 900px) {
  .package-context-bar {
    grid-template-columns: 1fr;
  }
}
</style>
