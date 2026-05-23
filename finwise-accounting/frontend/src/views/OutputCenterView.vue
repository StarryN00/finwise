<template>
  <PackageContextBar status-label="输出状态" :status-value="outputStateText" />

  <section class="output-grid">
    <article v-for="item in outputs" :key="item.title" class="output-card" :class="{ disabled: item.disabled() }">
      <div>
        <h2 class="section-title">{{ item.title }}</h2>
        <p class="caption">{{ item.description }}</p>
      </div>
      <StatusTag :status="item.status()" />
      <div class="output-actions">
        <el-button :disabled="item.disabled()" :loading="loadingAction === item.key" type="primary" @click="item.handler">
          {{ item.action }}
        </el-button>
        <el-button v-if="item.viewable" :disabled="item.viewDisabled()" @click="item.viewHandler">
          在线查看
        </el-button>
        <el-button v-if="item.downloadable" :disabled="item.downloadDisabled()" @click="item.downloadHandler">
          下载 PDF
        </el-button>
      </div>
    </article>

    <article class="output-card tax-module" :class="{ disabled: !activePackage }">
      <div class="tax-module__header">
        <div>
          <h2 class="section-title">辅助申报表</h2>
          <p class="caption">生成草稿后可在线核对，再下载电子税务申报辅助 Excel。</p>
        </div>
        <StatusTag :status="activePackage?.taxDraftStatus || 'DATA_INSUFFICIENT'" />
      </div>

      <div class="tax-flow">
        <div class="tax-flow__step" :class="{ done: activePackage?.taxDraftId }">
          <span>1</span>
          <strong>生成</strong>
          <small>汇总进销项明细</small>
        </div>
        <div class="tax-flow__step" :class="{ done: activePackage?.taxDraftId }">
          <span>2</span>
          <strong>查看/修改</strong>
          <small>核对申报口径</small>
        </div>
        <div class="tax-flow__step" :class="{ done: activePackage?.taxDraftStatus === 'EXPORTED' }">
          <span>3</span>
          <strong>下载</strong>
          <small>导出辅助 Excel</small>
        </div>
      </div>

      <div class="tax-actions">
        <el-button :disabled="!activePackage" :loading="loadingAction === 'tax'" type="primary" @click="generateTaxDraft">
          {{ activePackage?.taxDraftId ? '刷新申报草稿' : '生成申报草稿' }}
        </el-button>
        <el-button :disabled="!activePackage?.taxDraftId" :loading="loadingAction === 'taxDraftLoad'" @click="openTaxDraftEditor">
          查看/修改草稿
        </el-button>
        <el-button :disabled="!activePackage?.taxDraftId" :loading="loadingAction === 'taxExport'" @click="exportTaxDraft">
          下载申报 Excel
        </el-button>
      </div>
    </article>
  </section>

  <el-dialog v-model="taxDraftDialogVisible" title="申报草稿核对" width="640px">
    <div class="draft-context">
      <span>{{ activePackage?.company || '当前企业' }}</span>
      <strong>{{ activePackage?.period || '-' }}</strong>
    </div>
    <el-form label-position="top" class="draft-form">
      <el-form-item label="销项销售额">
        <el-input v-model="taxDraftForm.output_amount" />
      </el-form-item>
      <el-form-item label="销项税额">
        <el-input v-model="taxDraftForm.output_tax" />
      </el-form-item>
      <el-form-item label="进项金额">
        <el-input v-model="taxDraftForm.input_amount" />
      </el-form-item>
      <el-form-item label="进项税额">
        <el-input v-model="taxDraftForm.input_tax" />
      </el-form-item>
    </el-form>
    <div v-if="taxDraftWarnings.length" class="draft-warning">
      {{ taxDraftWarnings.join('；') }}
    </div>
    <template #footer>
      <el-button :disabled="!activePackage?.taxDraftId" @click="openTaxDraftPreview">打开在线预览</el-button>
      <el-button @click="taxDraftDialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="loadingAction === 'taxDraftSave'" @click="saveTaxDraftEdits">保存草稿</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import PackageContextBar from '../components/PackageContextBar.vue'
import StatusTag from '../components/StatusTag.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const loadingAction = ref('')
const taxDraftDialogVisible = ref(false)
const taxDraftWarnings = ref([])
const taxDraftForm = reactive({
  output_amount: '',
  output_tax: '',
  input_amount: '',
  input_tax: '',
})
const activePackage = computed(() => workspace.activePackage)
const outputStateText = computed(() => {
  if (!activePackage.value) return '未创建'
  if (activePackage.value.reportId && activePackage.value.reportStatus === 'READY') return '健康报告已生成'
  if (activePackage.value.reportId) return '健康报告数据不足'
  if (activePackage.value.taxDraftId) return '申报草稿已生成'
  if (activePackage.value.statementId) return '账目报表已生成'
  return '等待生成'
})

const outputs = [
  {
    key: 'statement',
    title: '每月账目与报表',
    description: '基于已确认流水和发票生成资产负债、利润表估算',
    status: () => activePackage.value?.statementId ? 'READY_TO_EXPORT' : 'DATA_INSUFFICIENT',
    action: '生成报表',
    disabled: () => !activePackage.value,
    handler: () => runAction('statement', () => workspace.generateStatement(activePackage.value.id), '报表已生成'),
    viewable: true,
    viewDisabled: () => !activePackage.value?.statementId,
    viewHandler: () => openStatementView(),
  },
  {
    key: 'report',
    title: '完整健康诊断报告',
    description: '偿债、盈利、现金流、税务风险 8 段诊断',
    status: () => activePackage.value?.reportStatus || 'DATA_INSUFFICIENT',
    action: '生成报告',
    disabled: () => !activePackage.value,
    handler: () => runAction('report', () => workspace.generateHealthReport(activePackage.value.id), '健康报告已生成'),
    viewable: true,
    viewDisabled: () => !activePackage.value?.reportId,
    viewHandler: () => openHealthReportView(),
    downloadable: true,
    downloadDisabled: () => !activePackage.value?.reportId || activePackage.value?.reportStatus !== 'READY',
    downloadHandler: () => downloadHealthReportPdf(),
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

function generateTaxDraft() {
  if (!activePackage.value?.id) return
  return runAction('tax', () => workspace.generateVatDraft(activePackage.value.id), '申报草稿已生成')
}

function exportTaxDraft() {
  if (!activePackage.value?.taxDraftId) return
  return runAction('taxExport', () => workspace.exportTaxDraft(activePackage.value.taxDraftId), '申报 Excel 已下载')
}

async function openTaxDraftEditor() {
  if (!activePackage.value?.taxDraftId) return
  loadingAction.value = 'taxDraftLoad'
  try {
    const response = await api.tax.getDraft(activePackage.value.taxDraftId)
    Object.assign(taxDraftForm, {
      output_amount: response.data.data.output_amount || '0.00',
      output_tax: response.data.data.output_tax || '0.00',
      input_amount: response.data.data.input_amount || '0.00',
      input_tax: response.data.data.input_tax || '0.00',
    })
    taxDraftWarnings.value = response.data.data.warnings || []
    taxDraftDialogVisible.value = true
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '申报草稿加载失败')
  } finally {
    loadingAction.value = ''
  }
}

async function saveTaxDraftEdits() {
  if (!activePackage.value?.taxDraftId) return
  loadingAction.value = 'taxDraftSave'
  try {
    const response = await api.tax.updateDraft(activePackage.value.taxDraftId, { ...taxDraftForm })
    Object.assign(taxDraftForm, {
      output_amount: response.data.data.output_amount,
      output_tax: response.data.data.output_tax,
      input_amount: response.data.data.input_amount,
      input_tax: response.data.data.input_tax,
    })
    taxDraftWarnings.value = response.data.data.warnings || []
    await workspace.loadWorkspace()
    ElMessage.success('申报草稿已保存')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '申报草稿保存失败')
  } finally {
    loadingAction.value = ''
  }
}

function openStatementView() {
  if (!activePackage.value?.id) return
  window.open(api.statements.viewUrl(activePackage.value.id), '_blank', 'noopener')
}

function openTaxDraftPreview() {
  if (!activePackage.value?.taxDraftId) return
  window.open(api.tax.viewDraftUrl(activePackage.value.taxDraftId), '_blank', 'noopener')
}

function openHealthReportView() {
  if (!activePackage.value?.reportId) return
  window.open(api.reports.viewHealthUrl(activePackage.value.reportId), '_blank', 'noopener')
}

function downloadHealthReportPdf() {
  if (!activePackage.value?.reportId) return
  window.open(api.reports.downloadHealthPdfUrl(activePackage.value.reportId), '_blank', 'noopener')
}
</script>

<style scoped>
.output-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
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

.output-actions {
  display: grid;
  gap: 10px;
}

.output-actions :deep(.el-button) {
  width: 100%;
  margin-left: 0;
}

.tax-module {
  gap: 16px;
}

.tax-module__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.tax-flow {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.tax-flow__step {
  display: grid;
  gap: 4px;
  min-height: 76px;
  padding: 12px;
  border: 1px solid var(--fw-line);
  border-radius: 8px;
  background: var(--fw-surface-muted);
}

.tax-flow__step span {
  display: inline-grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  color: var(--fw-text-muted);
  background: #eef2f7;
  font-size: 12px;
  font-weight: 700;
}

.tax-flow__step strong {
  font-size: 13px;
}

.tax-flow__step small {
  color: var(--fw-text-muted);
  line-height: 1.4;
}

.tax-flow__step.done {
  border-color: #b9dcff;
  background: #eef6ff;
}

.tax-flow__step.done span {
  color: #fff;
  background: var(--fw-primary);
}

.tax-actions {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
}

.tax-actions :deep(.el-button) {
  width: 100%;
  margin-left: 0;
}

.draft-context {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  padding: 12px;
  border: 1px solid var(--fw-line);
  border-radius: 8px;
  background: var(--fw-surface-muted);
}

.draft-context span {
  color: var(--fw-text-muted);
}

.draft-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 16px;
}

.draft-warning {
  padding: 10px 12px;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  color: #9a3412;
  background: #fff7ed;
}

@media (max-width: 960px) {
  .output-grid,
  .tax-flow,
  .tax-actions,
  .draft-form {
    grid-template-columns: 1fr;
  }
}
</style>
