<template>
  <section class="output-grid">
    <article v-for="item in outputs" :key="item.title" class="output-card" :class="{ disabled: item.disabled() }">
      <div>
        <h2 class="section-title">{{ item.title }}</h2>
        <p class="caption">{{ item.description }}</p>
      </div>
      <StatusTag :status="item.status()" />
      <el-button :disabled="item.disabled()" :loading="loadingAction === item.key" type="primary" @click="item.handler">
        {{ item.action }}
      </el-button>
    </article>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import StatusTag from '../components/StatusTag.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const loadingAction = ref('')
const activePackage = computed(() => workspace.activePackage)

const outputs = [
  {
    key: 'statement',
    title: '每月账目与报表',
    description: '基于已确认流水和发票生成资产负债、利润表估算',
    status: () => activePackage.value?.pending === 0 ? 'READY_TO_EXPORT' : 'PENDING_CONFIRMATION',
    action: '生成报表',
    disabled: () => !activePackage.value,
    handler: () => runAction('statement', () => workspace.generateStatement(activePackage.value.id), '报表已生成'),
  },
  {
    key: 'tax',
    title: '申报辅助 Excel',
    description: '增值税及附加税复制表',
    status: () => activePackage.value?.taxDraftStatus || 'DATA_INSUFFICIENT',
    action: '生成申报草稿',
    disabled: () => !activePackage.value,
    handler: () => runAction('tax', () => workspace.generateVatDraft(activePackage.value.id), '申报草稿已生成'),
  },
  {
    key: 'export',
    title: '导出申报文件',
    description: '下载电子税务申报辅助 Excel',
    status: () => activePackage.value?.taxDraftId ? 'READY_TO_EXPORT' : 'DATA_INSUFFICIENT',
    action: '导出 Excel',
    disabled: () => !activePackage.value?.taxDraftId,
    handler: () => runAction('export', () => workspace.exportTaxDraft(activePackage.value.taxDraftId), '导出文件已生成'),
  },
  {
    key: 'report',
    title: '完整健康诊断报告',
    description: '偿债、盈利、现金流、税务风险 8 段诊断',
    status: () => activePackage.value?.reportStatus || 'DATA_INSUFFICIENT',
    action: '生成报告',
    disabled: () => !activePackage.value,
    handler: () => runAction('report', () => workspace.generateHealthReport(activePackage.value.id), '健康报告已生成'),
  },
]

async function runAction(key, action, successText) {
  loadingAction.value = key
  try {
    await action()
    ElMessage.success(successText)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '操作失败')
  } finally {
    loadingAction.value = ''
  }
}
</script>

<style scoped>
.output-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.output-card {
  display: grid;
  align-content: space-between;
  gap: 18px;
  min-height: 190px;
  padding: 18px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.output-card.disabled {
  background: var(--fw-surface-muted);
}

.output-card .caption {
  margin: 8px 0 0;
}

@media (max-width: 960px) {
  .output-grid {
    grid-template-columns: 1fr;
  }
}
</style>
