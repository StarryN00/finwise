<template>
  <PackageContextBar
    aria-label="当前操作主体"
    status-label="接口标准"
    status-value="GB/T24589-2010"
  />

  <section class="historical-import-panel">
    <div class="panel-heading">
      <div>
        <h2 class="section-title">历史账套导入</h2>
        <p class="caption">导入企业年度序时账与余额表，形成可追溯的历史账目底稿。</p>
      </div>
      <el-tag type="info">审计接口 GB/T24589-2010</el-tag>
    </div>

    <el-form class="historical-form" label-width="92px">
      <el-form-item label="企业">
        <el-select v-model="form.enterpriseId" filterable placeholder="选择企业">
          <el-option
            v-for="enterprise in workspace.enterprises"
            :key="enterprise.id"
            :label="enterprise.name"
            :value="enterprise.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="会计年度">
        <el-input-number v-model="form.fiscalYear" :min="2000" :max="2100" controls-position="right" />
      </el-form-item>
    </el-form>

    <div class="file-grid">
      <article class="file-tile">
        <div>
          <strong>序时账</strong>
          <small>{{ ledgerFile?.name || '支持 .xls / .xlsx，包含日期、凭证字号、科目、借贷金额' }}</small>
        </div>
        <input ref="ledgerInput" class="file-input" type="file" accept=".xls,.xlsx" @change="selectLedgerFile" />
        <el-button @click="openLedgerPicker">选择序时账</el-button>
      </article>
      <article class="file-tile">
        <div>
          <strong>余额表</strong>
          <small>{{ balanceFile?.name || '支持 .xls / .xlsx，包含期初、本期、期末借贷余额' }}</small>
        </div>
        <input ref="balanceInput" class="file-input" type="file" accept=".xls,.xlsx" @change="selectBalanceFile" />
        <el-button @click="openBalancePicker">选择余额表</el-button>
      </article>
    </div>

    <div class="action-row">
      <el-button type="primary" :loading="isSubmitting" @click="submitHistoricalImport">导入历史账套</el-button>
      <span v-if="lastFeedback" class="feedback-text">{{ lastFeedback }}</span>
    </div>
  </section>

  <DataTableShell
    title="导入批次"
    description="显示最近一次历史账套导入后的结构化行数、借贷校验和异常样例。"
  >
    <div class="historical-summary-scroll">
      <el-table :data="summaryRows" class="historical-summary-table" stripe>
        <el-table-column prop="label" label="指标" width="180" />
        <el-table-column prop="value" label="结果" min-width="220" show-overflow-tooltip />
        <el-table-column prop="note" label="说明" min-width="360" show-overflow-tooltip />
      </el-table>
    </div>
  </DataTableShell>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import DataTableShell from '../components/DataTableShell.vue'
import PackageContextBar from '../components/PackageContextBar.vue'
import { api } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const now = new Date()
const form = reactive({
  enterpriseId: '',
  fiscalYear: now.getFullYear() - 1,
})
const ledgerInput = ref(null)
const balanceInput = ref(null)
const ledgerFile = ref(null)
const balanceFile = ref(null)
const isSubmitting = ref(false)
const importResult = ref(null)
const lastFeedback = ref('')

watch(
  () => workspace.enterprises,
  (enterprises) => {
    if (!form.enterpriseId && enterprises.length) {
      form.enterpriseId = enterprises[0].id
    }
  },
  { immediate: true },
)

onMounted(() => {
  if (!workspace.enterprises.length) {
    workspace.loadWorkspace()
  }
})

const summaryRows = computed(() => {
  const result = importResult.value
  if (!result) return []
  const summary = result.validation_summary || {}
  return [
    { label: '导入状态', value: statusLabel(result.status), note: '导入结果使用中文状态展示，避免暴露后端枚举。' },
    { label: '序时账行数', value: String(result.created_ledger_rows), note: '已排除合计、编制单位等页脚行。' },
    { label: '余额表行数', value: String(result.created_balance_rows), note: '已排除小计与合计行，仅保留科目行。' },
    { label: '凭证数量', value: String(summary.voucher_count ?? 0), note: '按日期和凭证字号归并后的凭证数。' },
    { label: '序时账借方合计', value: moneyText(summary.ledger_debit_total), note: '允许红字或冲销产生的负数金额。' },
    { label: '序时账贷方合计', value: moneyText(summary.ledger_credit_total), note: '与借方合计一致时，年度序时账整体平衡。' },
    { label: '余额表本期借方', value: moneyText(summary.balance_period_debit_total), note: '父子科目同时存在，不能直接作为报表合计使用。' },
    { label: '余额表本期贷方', value: moneyText(summary.balance_period_credit_total), note: '用于审计追溯和与序时账交叉检查。' },
    { label: '借贷不平凭证', value: String(summary.unbalanced_voucher_count ?? 0), note: unbalancedVoucherNote(summary) },
  ]
})

function openLedgerPicker() {
  ledgerInput.value?.click()
}

function openBalancePicker() {
  balanceInput.value?.click()
}

function selectLedgerFile(event) {
  ledgerFile.value = event.target.files?.[0] || null
}

function selectBalanceFile(event) {
  balanceFile.value = event.target.files?.[0] || null
}

async function submitHistoricalImport() {
  if (!form.enterpriseId) {
    ElMessage.warning('请先选择企业')
    return
  }
  if (!ledgerFile.value || !balanceFile.value) {
    ElMessage.warning('请同时选择序时账和余额表')
    return
  }
  isSubmitting.value = true
  lastFeedback.value = ''
  try {
    const formData = new FormData()
    formData.append('fiscal_year', String(form.fiscalYear))
    formData.append('ledger_file', ledgerFile.value)
    formData.append('balance_file', balanceFile.value)
    const response = await api.historicalImports.importGbt24589(form.enterpriseId, formData)
    importResult.value = response.data
    lastFeedback.value = `${form.fiscalYear} 年历史账套已导入：序时账 ${response.data.created_ledger_rows} 行，余额表 ${response.data.created_balance_rows} 行`
    ElMessage.success('历史账套已导入')
  } catch (error) {
    const detail = error?.response?.data?.detail || error?.message || '历史账套导入失败'
    lastFeedback.value = translateImportError(detail)
    ElMessage.error('历史账套导入失败')
  } finally {
    isSubmitting.value = false
  }
}

function statusLabel(status) {
  const labels = {
    IMPORTED: '已导入',
    IMPORTED_WITH_ERRORS: '已导入，存在异常',
    FAILED: '导入失败',
  }
  return labels[status] || '未知状态'
}

function moneyText(value) {
  if (value === undefined || value === null || value === '') return '-'
  return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function unbalancedVoucherNote(summary) {
  const samples = summary.unbalanced_voucher_samples || []
  if (!samples.length) return '所有按凭证字号归并的凭证均借贷平衡。'
  return samples.map((item) => `${item.voucher_date} ${item.voucher_no}`).join('；')
}

function translateImportError(message) {
  return String(message)
    .replace('Only .xlsx and .xls files are supported.', '仅支持 .xlsx、.xls 文件')
    .replace('Could not read import file:', '无法读取导入文件：')
    .replace('Enterprise not found.', '未找到企业')
}
</script>

<style scoped>
.historical-import-panel {
  display: grid;
  gap: 18px;
  padding: 16px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
}

.panel-heading,
.action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.historical-form {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) 220px;
  gap: 12px;
  max-width: 760px;
}

.file-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.file-tile {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 120px;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius-sm);
  background: #fbfcfe;
}

.file-tile strong,
.file-tile small {
  display: block;
}

.file-tile small {
  margin-top: 4px;
  color: var(--fw-text-muted);
  line-height: 1.4;
}

.file-input {
  display: none;
}

.feedback-text {
  color: var(--fw-text-muted);
  font-size: 13px;
}

.historical-summary-scroll {
  width: 100%;
  overflow-x: auto;
}

.historical-summary-table {
  width: 100%;
  min-width: 980px;
}

@media (max-width: 860px) {
  .historical-form,
  .file-grid {
    grid-template-columns: 1fr;
  }

  .panel-heading,
  .action-row {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
