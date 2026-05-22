<template>
  <section class="step-grid">
    <article v-for="(step, index) in steps" :key="step" class="step-card">
      <span>{{ index + 1 }}</span>
      <strong>{{ step }}</strong>
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
      <div class="upload-actions">
        <input ref="bankInput" class="file-input" type="file" accept=".xlsx,.xls,.csv" @change="uploadBankStatement" />
        <input ref="inputInvoiceInput" class="file-input" type="file" accept=".xlsx,.xls,.csv" @change="uploadInputInvoices" />
        <input ref="outputInvoiceInput" class="file-input" type="file" accept=".xlsx,.xls,.csv" @change="uploadOutputInvoices" />
        <el-button :loading="uploadingType === 'bank'" @click="bankInput?.click()">上传银行流水</el-button>
        <el-button :loading="uploadingType === 'input'" @click="inputInvoiceInput?.click()">上传进项明细</el-button>
        <el-button :loading="uploadingType === 'output'" @click="outputInvoiceInput?.click()">上传销项明细</el-button>
      </div>
      <p v-if="lastUploadResult" class="upload-result">{{ lastUploadResult }}</p>
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
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import MetricCard from '../components/MetricCard.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const steps = ['导入资料', '解析结果', '匹配确认', '账目明细', '预估报表', '申报辅助', '老板简报']
const uploadingType = ref('')
const lastUploadResult = ref('')
const bankInput = ref(null)
const inputInvoiceInput = ref(null)
const outputInvoiceInput = ref(null)

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
  lastUploadResult.value = ''
  try {
    const formData = new FormData()
    formData.append('file', file)
    const response = await action(activePackage.id, formData)
    const created = response.data.created ?? 0
    const errors = response.data.errors?.length ?? 0
    lastUploadResult.value = `${file.name}：导入 ${created} 条，错误 ${errors} 条`
    await workspace.loadWorkspace()
    ElMessage.success('资料已上传并解析')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '资料上传失败')
  } finally {
    uploadingType.value = ''
  }
}
</script>

<style scoped>
.step-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 10px;
}

.step-card,
.panel {
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.step-card {
  min-height: 82px;
  padding: 12px;
}

.step-card span {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: var(--fw-radius-sm);
  color: var(--fw-brand-dark);
  background: var(--fw-brand-soft);
  font-size: 12px;
  font-weight: 800;
}

.step-card strong {
  display: block;
  margin-top: 10px;
  font-size: 13px;
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

.upload-actions {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.file-input {
  display: none;
}

.upload-actions :deep(.el-button) {
  width: 100%;
}

.upload-result {
  margin: 14px 0 0;
  color: var(--fw-text-muted);
  font-size: 13px;
}

@media (max-width: 1100px) {
  .step-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .workspace-grid {
    grid-template-columns: 1fr;
  }
}
</style>
