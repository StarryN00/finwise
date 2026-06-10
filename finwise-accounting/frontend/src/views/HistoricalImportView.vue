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
      <el-form-item label="起始月份">
        <el-select v-model="form.periodStartMonth" placeholder="选择起始月份">
          <el-option
            v-for="month in monthOptions"
            :key="month.value"
            :label="month.label"
            :value="month.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="截止月份">
        <el-select v-model="form.periodEndMonth" placeholder="选择截止月份">
          <el-option
            v-for="month in monthOptions"
            :key="month.value"
            :label="month.label"
            :value="month.value"
          />
        </el-select>
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
    title="导入记录"
    description="记录每次历史账套导入的时间、账套期间、数据时间范围、文件名称和导入结果。"
  >
    <div class="historical-record-scroll">
      <el-table v-loading="isLoadingRecords" :data="importRecords" class="historical-record-table" stripe>
        <el-table-column prop="createdAtLabel" label="导入时间" width="156" />
        <el-table-column prop="periodLabel" label="账套期间" width="136" />
        <el-table-column prop="dataRangeLabel" label="数据时间范围" width="190" show-overflow-tooltip />
        <el-table-column label="结果" width="140">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" effect="light">{{ row.statusLabel }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="数据量" width="158">
          <template #default="{ row }">
            <div class="record-stack">
              <span>{{ row.ledgerRowsLabel }}</span>
              <span>{{ row.balanceRowsLabel }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="源文件" min-width="320" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="record-stack">
              <span>序时账：{{ row.ledgerFileName }}</span>
              <span>余额表：{{ row.balanceFileName }}</span>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </DataTableShell>

  <DataTableShell
    title="导入批次校验"
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
  periodStartMonth: 1,
  periodEndMonth: 12,
})
const ledgerInput = ref(null)
const balanceInput = ref(null)
const ledgerFile = ref(null)
const balanceFile = ref(null)
const isSubmitting = ref(false)
const importResult = ref(null)
const lastFeedback = ref('')
const importRecords = ref([])
const isLoadingRecords = ref(false)
const monthOptions = Array.from({ length: 12 }, (_, index) => {
  const value = index + 1
  return { value, label: `${value} 月` }
})

watch(
  () => workspace.enterprises,
  (enterprises) => {
    if (!form.enterpriseId && enterprises.length) {
      form.enterpriseId = enterprises[0].id
    }
  },
  { immediate: true },
)

watch(
  () => form.enterpriseId,
  (enterpriseId) => {
    if (enterpriseId) {
      loadImportRecords(enterpriseId)
    }
  },
)

onMounted(() => {
  if (!workspace.enterprises.length) {
    workspace.loadWorkspace()
  } else if (form.enterpriseId) {
    loadImportRecords(form.enterpriseId)
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
  if (form.periodStartMonth > form.periodEndMonth) {
    ElMessage.warning('起始月份不能晚于截止月份')
    return
  }
  isSubmitting.value = true
  lastFeedback.value = ''
  try {
    const formData = new FormData()
    formData.append('fiscal_year', String(form.fiscalYear))
    formData.append('period_start_month', String(form.periodStartMonth))
    formData.append('period_end_month', String(form.periodEndMonth))
    formData.append('ledger_file', ledgerFile.value)
    formData.append('balance_file', balanceFile.value)
    const response = await api.historicalImports.importGbt24589(form.enterpriseId, formData)
    importResult.value = response.data
    lastFeedback.value = `${periodLabel()} 历史账套已导入：序时账 ${response.data.created_ledger_rows} 行，余额表 ${response.data.created_balance_rows} 行`
    await loadImportRecords(form.enterpriseId)
    ElMessage.success('历史账套已导入')
  } catch (error) {
    const detail = error?.response?.data?.detail || error?.message || '历史账套导入失败'
    lastFeedback.value = translateImportError(detail)
    ElMessage.error('历史账套导入失败')
  } finally {
    isSubmitting.value = false
  }
}

async function loadImportRecords(enterpriseId = form.enterpriseId) {
  if (!enterpriseId) return
  isLoadingRecords.value = true
  try {
    const response = await api.historicalImports.list(enterpriseId)
    importRecords.value = (response.data || []).map((record) => ({
      ...record,
      createdAtLabel: formatDateTime(record.created_at),
      periodLabel: importPeriodLabel(record),
      dataRangeLabel: importDataRangeLabel(record),
      statusLabel: statusLabel(record.status),
      ledgerRowsLabel: `序时账 ${record.created_ledger_rows} 行`,
      balanceRowsLabel: `余额表 ${record.created_balance_rows} 行`,
      ledgerFileName: record.ledger_filename || '-',
      balanceFileName: record.balance_filename || '-',
    }))
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '导入记录加载失败')
  } finally {
    isLoadingRecords.value = false
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

function statusTagType(status) {
  const types = {
    IMPORTED: 'success',
    IMPORTED_WITH_ERRORS: 'warning',
    FAILED: 'danger',
  }
  return types[status] || 'info'
}

function importPeriodLabel(record) {
  if (record.period_start_month === 1 && record.period_end_month === 12) return `${record.fiscal_year} 年`
  return `${record.fiscal_year} 年 ${record.period_start_month} 月至 ${record.period_end_month} 月`
}

function importDataRangeLabel(record) {
  const metadata = record.source_metadata || {}
  const ledgerPeriod = metadata.ledger_period_text
  const balancePeriod = metadata.balance_period_text
  if (ledgerPeriod && balancePeriod && ledgerPeriod !== balancePeriod) {
    return `序时账 ${ledgerPeriod} / 余额表 ${balancePeriod}`
  }
  return ledgerPeriod || balancePeriod || importPeriodText(record)
}

function importPeriodText(record) {
  const startMonth = String(record.period_start_month).padStart(2, '0')
  const endMonth = String(record.period_end_month).padStart(2, '0')
  return `${record.fiscal_year}年${startMonth}月至${record.fiscal_year}年${endMonth}月`
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
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

function periodLabel() {
  if (form.periodStartMonth === 1 && form.periodEndMonth === 12) return `${form.fiscalYear} 年`
  return `${form.fiscalYear} 年 ${form.periodStartMonth} 月至 ${form.periodEndMonth} 月`
}

function translateImportError(message) {
  return String(message)
    .replace('Only .xlsx and .xls files are supported.', '仅支持 .xlsx、.xls 文件')
    .replace('Could not read import file:', '无法读取导入文件：')
    .replace('Uploaded historical files do not match the selected fiscal year.', '上传的历史账套期间与选择的会计年度不一致')
    .replace('Uploaded historical files do not match the selected accounting period.', '上传的历史账套期间与选择的会计期间不一致')
    .replace('Selected historical import period month is out of supported range.', '选择的月份超出支持范围')
    .replace('Selected historical import period start month cannot be after end month.', '起始月份不能晚于截止月份')
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
  grid-template-columns: minmax(260px, 1fr) 180px 180px 180px;
  gap: 12px;
  max-width: 980px;
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

.historical-record-scroll {
  width: 100%;
  overflow-x: auto;
}

.historical-summary-table {
  width: 100%;
  min-width: 980px;
}

.historical-record-table {
  width: 100%;
  min-width: 1100px;
}

.record-stack {
  display: grid;
  gap: 2px;
  color: var(--fw-text);
  font-size: 13px;
  line-height: 1.45;
}

.record-stack span + span {
  color: var(--fw-text-muted);
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
