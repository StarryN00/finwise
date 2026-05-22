<template>
  <section class="active-package-context">
    <div>
      <span class="context-label">当前处理企业</span>
      <strong>{{ activePackage?.company || '暂无月度工作包' }}</strong>
    </div>
    <div>
      <span class="context-label">工作期间</span>
      <strong>{{ activePackage?.period || '-' }}</strong>
    </div>
    <div>
      <span class="context-label">当前阶段</span>
      <strong>{{ currentStep.title }}</strong>
    </div>
  </section>

  <section class="workflow-timeline" aria-label="月度工作流程">
    <article
      v-for="(step, index) in workflowSteps"
      :key="step.title"
      class="timeline-step"
      :class="{
        'is-done': step.status === 'done',
        'is-current': step.status === 'current',
        'is-todo': step.status === 'todo',
      }"
    >
      <span class="step-marker">{{ index + 1 }}</span>
      <div class="step-copy">
        <strong>{{ step.title }}</strong>
        <small>{{ step.hint }}</small>
      </div>
      <span class="step-state">{{ step.statusLabel }}</span>
    </article>
  </section>

  <section class="workspace-grid">
    <div class="panel">
      <h2 class="section-title">缺失资料清单</h2>
      <ul class="checklist">
        <li v-for="item in workspace.missingChecklist" :key="item.label">
          <el-checkbox :model-value="item.done" disabled>{{ item.label }}</el-checkbox>
        </li>
      </ul>
    </div>
    <div class="panel upload-panel">
      <h2 class="section-title">补充资料</h2>
      <p class="caption">选择当前工作包需要的资料，上传后会自动解析并刷新缺失清单。</p>
      <div class="upload-list">
        <input ref="bankInput" class="file-input" type="file" accept=".xlsx,.xls,.csv" @change="uploadBankStatement" />
        <input ref="inputInvoiceInput" class="file-input" type="file" accept=".xlsx,.xls,.csv" @change="uploadInputInvoices" />
        <input ref="outputInvoiceInput" class="file-input" type="file" accept=".xlsx,.xls,.csv" @change="uploadOutputInvoices" />
        <div v-for="item in uploadItems" :key="item.type" class="upload-row">
          <div class="upload-item-main">
            <strong>{{ item.label }}</strong>
            <small>{{ item.description }}</small>
            <p v-if="uploadResults[item.type]" class="upload-result">{{ uploadResults[item.type] }}</p>
            <p v-if="uploadErrors[item.type]" class="upload-item-error">{{ uploadErrors[item.type] }}</p>
          </div>
          <span class="upload-state" :class="{ 'is-ready': item.done }">{{ item.done ? '已导入' : '待补充' }}</span>
          <el-button :loading="uploadingType === item.type" @click="openFilePicker(item.type)">
            {{ item.action }}
          </el-button>
        </div>
      </div>
    </div>
    <div class="panel">
      <h2 class="section-title">确认进度</h2>
      <MetricCard
        label="待人工确认"
        :value="String(workspace.activePackage?.pending ?? 0)"
        subtext="包含未匹配流水、发票和规则分类"
        tone="warning"
      />
    </div>
  </section>

  <section class="next-action-panel">
    <div>
      <h2 class="section-title">下一步</h2>
      <p class="caption">{{ nextActionHint }}</p>
    </div>
    <div class="next-actions">
      <el-button
        v-for="action in nextActions"
        :key="action.key"
        :type="action.primary ? 'primary' : 'default'"
        :loading="loadingAction === action.key"
        :disabled="action.disabled"
        @click="runNextAction(action)"
      >
        {{ action.label }}
      </el-button>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import MetricCard from '../components/MetricCard.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const router = useRouter()
const uploadingType = ref('')
const loadingAction = ref('')
const uploadResults = reactive({ bank: '', input: '', output: '' })
const uploadErrors = reactive({ bank: '', input: '', output: '' })
const bankInput = ref(null)
const inputInvoiceInput = ref(null)
const outputInvoiceInput = ref(null)
const activePackage = computed(() => workspace.activePackage)

const workflowFlags = computed(() => {
  const hasAllSourceData = isChecklistDone('银行流水') && isChecklistDone('销项明细') && isChecklistDone('进项明细')
  const hasParsedRows = hasAllSourceData && workspace.accountRows.length > 0
  const hasConfirmed = hasParsedRows && isChecklistDone('人工确认')
  const hasHealthReport = isChecklistDone('健康报告数据')
  const hasTaxDraft = Boolean(activePackage.value?.taxDraftId)
  return { hasAllSourceData, hasParsedRows, hasConfirmed, hasHealthReport, hasTaxDraft }
})

const workflowSteps = computed(() => {
  const { hasAllSourceData, hasParsedRows, hasConfirmed, hasHealthReport, hasTaxDraft } = workflowFlags.value
  const definitions = [
    { title: '导入资料', done: hasAllSourceData, hint: hasAllSourceData ? '三类资料已齐' : '等待补充资料' },
    { title: '解析结果', done: hasParsedRows, hint: hasParsedRows ? '已生成结构化数据' : '上传后自动解析' },
    { title: '匹配确认', done: hasConfirmed, hint: hasConfirmed ? '无需人工处理' : `${workspace.activePackage?.pending ?? 0} 项待确认` },
    { title: '账目明细', done: hasConfirmed, hint: hasConfirmed ? '流水发票已汇总' : '等待确认完成' },
    { title: '预估报表', done: hasTaxDraft || hasHealthReport, hint: hasTaxDraft ? '已生成申报草稿' : '确认后生成' },
    { title: '申报辅助', done: hasTaxDraft, hint: hasTaxDraft ? '可导出申报表' : '等待报表数据' },
    { title: '老板简报', done: hasHealthReport, hint: hasHealthReport ? '健康报告已生成' : '等待完整数据' },
  ]
  const currentIndex = definitions.findIndex((step) => !step.done)
  return definitions.map((step, index) => stepState(step.title, step.done, index === currentIndex, step.hint))
})

const currentStep = computed(() => workflowSteps.value.find((step) => step.status === 'current') || workflowSteps.value.at(-1) || { title: '暂无工作包' })

const nextActionHint = computed(() => {
  const { hasAllSourceData, hasParsedRows, hasConfirmed, hasTaxDraft, hasHealthReport } = workflowFlags.value
  if (!activePackage.value) return '先创建本月工作包，再导入银行流水、进项和销项明细。'
  if (!hasAllSourceData) return '请先补齐缺失资料。资料齐全后系统才能继续解析和匹配。'
  if (!hasParsedRows) return '资料已经齐全，下一步运行匹配，生成待确认账目明细。'
  if (!hasConfirmed) return '还有待确认明细，请进入账目明细处理未匹配流水、发票和分类。'
  if (!hasTaxDraft) return '账目已确认，可以生成每月账目报表和申报草稿。'
  if (!hasHealthReport) return '申报草稿已生成，可以继续生成老板看的财务健康报告。'
  return '本月核心输出已完成，可以到输出中心导出或复核结果。'
})

const nextActions = computed(() => {
  const { hasAllSourceData, hasParsedRows, hasConfirmed, hasTaxDraft, hasHealthReport } = workflowFlags.value
  const packageId = activePackage.value?.id
  if (!activePackage.value) return []
  if (!hasAllSourceData) {
    return [{ key: 'upload', label: '补充缺失资料', primary: true, handler: () => scrollToUploads() }]
  }
  if (!hasParsedRows) {
    return [{ key: 'matching', label: '运行匹配', primary: true, handler: () => workspace.runMatching(packageId) }]
  }
  if (!hasConfirmed) {
    return [{ key: 'account-details', label: '处理账目明细', primary: true, handler: () => router.push('/account-details') }]
  }
  if (!hasTaxDraft) {
    return [
      { key: 'statement', label: '生成每月账目报表', primary: false, handler: () => workspace.generateStatement(packageId) },
      { key: 'tax', label: '生成申报草稿', primary: true, handler: () => workspace.generateVatDraft(packageId) },
    ]
  }
  if (!hasHealthReport) {
    return [{ key: 'report', label: '生成财务健康报告', primary: true, handler: () => workspace.generateHealthReport(packageId) }]
  }
  return [{ key: 'output', label: '查看输出中心', primary: true, handler: () => router.push('/output-center') }]
})

const uploadItems = computed(() => [
  {
    type: 'bank',
    label: '银行流水',
    description: '支持 .xlsx/.xls/.csv，需包含日期、摘要、收入/支出金额等列',
    action: '上传银行流水',
    done: isChecklistDone('银行流水'),
  },
  {
    type: 'input',
    label: '进项明细',
    description: '电子税务局导出的进项发票明细',
    action: '上传进项明细',
    done: isChecklistDone('进项明细'),
  },
  {
    type: 'output',
    label: '销项明细',
    description: '电子税务局导出的销项发票明细',
    action: '上传销项明细',
    done: isChecklistDone('销项明细'),
  },
])

function uploadBankStatement(event) {
  return uploadSelectedFile(event, 'bank', (packageId, formData) => api.imports.bank(packageId, formData))
}

function uploadInputInvoices(event) {
  return uploadSelectedFile(event, 'input', (packageId, formData) => api.imports.inputInvoices(packageId, formData))
}

function uploadOutputInvoices(event) {
  return uploadSelectedFile(event, 'output', (packageId, formData) => api.imports.outputInvoices(packageId, formData))
}

async function uploadSelectedFile(event, type, action) {
  const file = event.target.files?.[0]
  if (!file) return
  try {
    await uploadPackageFile(type, file, action)
  } finally {
    event.target.value = ''
  }
}

async function uploadPackageFile(type, file, action) {
  const activePackage = workspace.activePackage
  if (!activePackage) {
    ElMessage.warning('请先创建月度工作包')
    return
  }
  uploadingType.value = type
  uploadResults[type] = ''
  uploadErrors[type] = ''
  try {
    const formData = new FormData()
    formData.append('file', file)
    const response = await action(activePackage.id, formData)
    const created = response.data.created ?? 0
    const errors = response.data.errors ?? []
    const batchErrors = response.data.batch_errors ?? []
    uploadResults[type] = `${file.name}：导入 ${created} 条，错误 ${errors.length + batchErrors.length} 条`
    if (errors.length || batchErrors.length || created === 0) {
      uploadErrors[type] = formatUploadError(type, errors, batchErrors, created)
    }
    await workspace.loadWorkspace()
    if (uploadErrors[type]) {
      ElMessage.warning('资料已上传，但有内容未能识别')
    } else {
      ElMessage.success('资料已上传并解析')
    }
  } catch (error) {
    uploadErrors[type] = formatUploadError(type, error)
    ElMessage.error('资料上传失败，请查看页面错误提示')
  } finally {
    uploadingType.value = ''
  }
}

function openFilePicker(type) {
  const inputByType = {
    bank: bankInput.value,
    input: inputInvoiceInput.value,
    output: outputInvoiceInput.value,
  }
  inputByType[type]?.click()
}

async function runNextAction(action) {
  loadingAction.value = action.key
  try {
    await action.handler()
    if (!['upload', 'account-details', 'output'].includes(action.key)) {
      ElMessage.success('操作已完成')
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '操作失败')
  } finally {
    loadingAction.value = ''
  }
}

function scrollToUploads() {
  document.querySelector('.upload-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function stepState(title, done, current, hint) {
  const status = done ? 'done' : current ? 'current' : 'todo'
  const statusLabel = done ? '已完成' : current ? '进行中' : '未开始'
  return { title, status, statusLabel, hint }
}

function isChecklistDone(label) {
  return Boolean(workspace.missingChecklist.find((item) => item.label === label)?.done)
}

function formatUploadError(type, errorOrRows, batchErrors = [], created = 0) {
  const prefix = type === 'bank' ? '银行流水解析失败' : type === 'input' ? '进项明细解析失败' : '销项明细解析失败'
  if (Array.isArray(errorOrRows)) {
    const rowMessages = errorOrRows.slice(0, 3).map((item) => `第 ${item.row} 行：${translateImportError(item.error)}`)
    const batchMessages = batchErrors.slice(0, 3).map((item) => translateImportError(item.error))
    const messages = [...batchMessages, ...rowMessages]
    if (messages.length) {
      return `${prefix}：${messages.join('；')}`
    }
    if (created === 0) {
      return `${prefix}：未识别到可导入数据。请确认表头包含交易日期、摘要、收入金额、支出金额等必要列，或换用标准导出模板。`
    }
  }
  const detail = errorOrRows?.response?.data?.detail || errorOrRows?.message || '资料上传失败'
  return `${prefix}：${translateImportError(detail)}`
}

function translateImportError(message) {
  const text = Array.isArray(message)
    ? message.map((item) => item.msg || item.message || JSON.stringify(item)).join('；')
    : typeof message === 'object' && message !== null
      ? JSON.stringify(message)
      : String(message)
  return text
    .replace('Only .csv, .xlsx, and .xls files are supported.', '仅支持 .csv、.xlsx、.xls 文件')
    .replace('Could not read import file:', '无法读取导入文件：')
    .replace('missing date value', '缺少交易日期')
    .replace('missing debit or credit amount', '缺少收入金额或支出金额')
    .replace('missing required decimal value:', '缺少必要金额字段：')
    .replace('missing required text value:', '缺少必要文本字段：')
}
</script>

<style scoped>
.active-package-context,
.next-action-panel {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.active-package-context strong {
  display: block;
  margin-top: 6px;
  color: var(--fw-text);
  font-size: 16px;
}

.context-label {
  color: var(--fw-text-muted);
  font-size: 12px;
}

.workflow-timeline {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 0;
  padding: 16px 18px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.panel {
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.timeline-step {
  position: relative;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  align-items: start;
  min-height: 76px;
  padding-right: 16px;
}

.timeline-step::before {
  position: absolute;
  top: 15px;
  left: 34px;
  right: 8px;
  height: 2px;
  background: var(--fw-line);
  content: '';
}

.timeline-step:last-child::before {
  display: none;
}

.step-marker {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--fw-line);
  border-radius: 999px;
  color: var(--fw-text-muted);
  background: #fff;
  font-size: 12px;
  font-weight: 800;
}

.step-copy {
  min-width: 0;
}

.step-copy strong {
  display: block;
  font-size: 13px;
}

.step-copy small {
  display: block;
  margin-top: 5px;
  color: var(--fw-text-muted);
  line-height: 1.4;
}

.step-state {
  grid-column: 2;
  width: fit-content;
  margin-top: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  color: var(--fw-text-muted);
  background: #f3f6fb;
  font-size: 12px;
}

.timeline-step.is-done .step-marker,
.timeline-step.is-done .step-state {
  color: #fff;
  border-color: #2f9461;
  background: #2f9461;
}

.timeline-step.is-current .step-marker,
.timeline-step.is-current .step-state {
  color: var(--fw-brand-dark);
  border-color: var(--fw-brand);
  background: var(--fw-brand-soft);
}

.timeline-step.is-done::before {
  background: #2f9461;
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(300px, 420px) 280px;
  gap: 16px;
}

.panel {
  padding: 16px;
}

.checklist {
  display: grid;
  gap: 8px;
  padding: 0;
  margin: 14px 0 0;
  list-style: none;
}

.upload-panel .caption {
  margin: 8px 0 0;
}

.upload-list {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.upload-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 64px 126px;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius-sm);
  background: #fbfcfe;
}

.upload-item-main {
  min-width: 0;
}

.upload-item-main strong {
  display: block;
  font-size: 14px;
}

.upload-item-main small {
  display: block;
  margin-top: 4px;
  color: var(--fw-text-muted);
  line-height: 1.4;
}

.upload-state {
  color: #9a5d00;
  font-size: 12px;
  text-align: center;
}

.upload-state.is-ready {
  color: #2f9461;
}

.file-input {
  display: none;
}

.upload-row :deep(.el-button) {
  width: 100%;
}

.upload-result {
  margin: 8px 0 0;
  color: var(--fw-text-muted);
  font-size: 13px;
}

.upload-item-error {
  margin: 8px 0 0;
  padding: 8px 10px;
  border: 1px solid #f6c7c7;
  border-radius: var(--fw-radius-sm);
  color: #9d1f1f;
  background: #fff5f5;
  font-size: 13px;
  line-height: 1.45;
}

.next-action-panel {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
}

.next-action-panel .caption {
  margin: 8px 0 0;
}

.next-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 1100px) {
  .workflow-timeline {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px 0;
  }

  .workspace-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .active-package-context,
  .next-action-panel {
    grid-template-columns: 1fr;
  }

  .next-actions {
    justify-content: stretch;
  }

  .next-actions :deep(.el-button) {
    width: 100%;
  }

  .workflow-timeline {
    grid-template-columns: 1fr;
  }

  .timeline-step::before {
    left: 15px;
    top: 34px;
    bottom: 8px;
    width: 2px;
    height: auto;
  }

  .upload-row {
    grid-template-columns: 1fr;
  }

  .upload-state {
    text-align: left;
  }
}
</style>
