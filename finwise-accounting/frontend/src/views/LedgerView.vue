<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'
import { formatAmount } from '../components/source-ledgers/ledgerFormatters'

const CONTEXT_STORAGE_KEY = 'finwise:ledger:context'
const pageSize = 20

const workspace = useWorkspaceStore()
const sourceMode = ref('monthly')
const selectedEnterpriseId = ref('')
const selectedPeriodPackageId = ref('')
const selectedAccountCode = ref('')
const historicalFiscalYear = ref(new Date().getFullYear())
const historicalStartMonth = ref(1)
const historicalEndMonth = ref(12)
const activeTab = ref('journal')
const keyword = ref('')
const currentPage = ref(1)
const isLoading = ref(false)

const summary = ref({
  confirmed_voucher_count: 0,
  pending_voucher_count: 0,
  entry_count: 0,
  is_final: true,
})
const accountOptions = ref([])
const journalRows = ref([])
const generalRows = ref([])
const detailRows = ref([])
const trialBalance = ref({
  rows: [],
  is_balanced: true,
  difference: '0.00',
  opening_debit_total: '0.00',
  opening_credit_total: '0.00',
  period_debit_total: '0.00',
  period_credit_total: '0.00',
  closing_debit_total: '0.00',
  closing_credit_total: '0.00',
})

const enterpriseOptions = computed(() => workspace.enterprises || [])
const periodOptions = computed(() => {
  const packages = workspace.workPackages || []
  if (!selectedEnterpriseId.value) return packages
  return packages.filter((item) => packageEnterpriseId(item) === selectedEnterpriseId.value)
})
const activePackage = computed(() => {
  return (workspace.workPackages || []).find((item) => item.id === selectedPeriodPackageId.value) || null
})
const monthOptions = Array.from({ length: 12 }, (_, index) => {
  const value = index + 1
  return { value, label: `${value} 月` }
})
const historicalParams = computed(() => ({
  fiscal_year: Number(historicalFiscalYear.value),
  period_start_month: Number(historicalStartMonth.value),
  period_end_month: Number(historicalEndMonth.value),
}))
const selectedPeriodLabel = computed(() => {
  if (sourceMode.value === 'historical') {
    if (Number(historicalStartMonth.value) === 1 && Number(historicalEndMonth.value) === 12) return `${historicalFiscalYear.value} 年`
    return `${historicalFiscalYear.value} 年 ${historicalStartMonth.value} 月至 ${historicalEndMonth.value} 月`
  }
  return activePackage.value?.period || '-'
})

const tabOptions = [
  { label: '序时账', name: 'journal' },
  { label: '总账', name: 'general' },
  { label: '明细账', name: 'detail' },
  { label: '余额表', name: 'trial' },
]

const columnSets = {
  journal: [
    { key: 'voucher_date', label: '凭证日期', width: '110px' },
    { key: 'voucher_number', label: '凭证号', width: '110px' },
    { key: 'summary', label: '摘要', minWidth: '180px' },
    { key: 'account_label', label: '会计科目', minWidth: '180px' },
    { key: 'direction_label', label: '方向', width: '80px' },
    { key: 'debit_amount', label: '借方金额', width: '120px', align: 'right', amount: true },
    { key: 'credit_amount', label: '贷方金额', width: '120px', align: 'right', amount: true },
    { key: 'source_type', label: '来源', width: '100px' },
  ],
  general: [
    { key: 'account_label', label: '会计科目', minWidth: '200px' },
    { key: 'account_category', label: '类别', width: '90px' },
    { key: 'opening_debit', label: '期初借方', width: '120px', align: 'right', amount: true },
    { key: 'opening_credit', label: '期初贷方', width: '120px', align: 'right', amount: true },
    { key: 'period_debit', label: '本期借方', width: '120px', align: 'right', amount: true },
    { key: 'period_credit', label: '本期贷方', width: '120px', align: 'right', amount: true },
    { key: 'balance_direction_label', label: '期末方向', width: '90px' },
    { key: 'closing_debit', label: '期末借方', width: '120px', align: 'right', amount: true },
    { key: 'closing_credit', label: '期末贷方', width: '120px', align: 'right', amount: true },
  ],
  detail: [
    { key: 'voucher_date', label: '凭证日期', width: '110px' },
    { key: 'voucher_number', label: '凭证号', width: '110px' },
    { key: 'summary', label: '摘要', minWidth: '190px' },
    { key: 'counter_account_display', label: '对方科目 / 辅助对象', minWidth: '260px' },
    { key: 'debit_amount', label: '借方金额', width: '120px', align: 'right', amount: true },
    { key: 'credit_amount', label: '贷方金额', width: '120px', align: 'right', amount: true },
    { key: 'balance_direction_label', label: '期末方向', width: '90px' },
    { key: 'balance', label: '余额', width: '120px', align: 'right', amount: true },
  ],
  trial: [
    { key: 'display_code', label: '科目编码', width: '120px' },
    { key: 'display_name', label: '科目名称', minWidth: '220px' },
    { key: 'opening_debit', label: '期初借方', width: '120px', align: 'right', amount: true },
    { key: 'opening_credit', label: '期初贷方', width: '120px', align: 'right', amount: true },
    { key: 'period_debit', label: '本期借方', width: '120px', align: 'right', amount: true },
    { key: 'period_credit', label: '本期贷方', width: '120px', align: 'right', amount: true },
    { key: 'closing_debit', label: '期末借方', width: '120px', align: 'right', amount: true },
    { key: 'closing_credit', label: '期末贷方', width: '120px', align: 'right', amount: true },
  ],
}

const currentColumns = computed(() => columnSets[activeTab.value] || columnSets.journal)
const currentRows = computed(() => {
  if (activeTab.value === 'general') return generalRows.value.map(withAccountLabel)
  if (activeTab.value === 'detail') return detailRows.value
  if (activeTab.value === 'trial') return (trialBalance.value.rows || []).map(withTrialDisplay)
  return journalRows.value.map(withAccountLabel)
})
const filteredRows = computed(() => {
  const searchText = keyword.value.trim().toLowerCase()
  if (!searchText) return currentRows.value
  return currentRows.value.filter((row) => rowSearchText(row).includes(searchText))
})
const pageCount = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / pageSize)))
const pagedRows = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredRows.value.slice(start, start + pageSize)
})
const paginationSummary = computed(
  () => `当前显示 ${pagedRows.value.length} 条 / 筛选结果 ${filteredRows.value.length} 条 / 原始总数 ${currentRows.value.length} 条`,
)
const activeAccountLabel = computed(() => {
  const account = accountOptions.value.find((item) => item.account_code === selectedAccountCode.value)
  return account ? `${account.account_code} ${account.account_name}` : '请选择科目'
})

onMounted(async () => {
  restoreContext()
  if (!workspace.workPackages.length) {
    await workspace.loadWorkspace(selectedPeriodPackageId.value || undefined)
  }
  ensureSelection()
})

watch(
  () => workspace.workPackages,
  () => ensureSelection(),
  { deep: true },
)

watch(selectedEnterpriseId, () => {
  if (sourceMode.value === 'historical') {
    loadLedgers()
    return
  }
  const current = activePackage.value
  if (current && packageEnterpriseId(current) === selectedEnterpriseId.value) return
  selectedPeriodPackageId.value = periodOptions.value[0]?.id || ''
})

watch(selectedPeriodPackageId, async (packageId) => {
  persistContext()
  currentPage.value = 1
  if (sourceMode.value === 'monthly' && packageId) {
    await loadLedgers()
  } else {
    resetLedgerData()
  }
})

watch(selectedAccountCode, async () => {
  currentPage.value = 1
  if (activeTab.value === 'detail' && canLoadLedgers()) {
    await loadDetailLedger()
  }
})

watch([sourceMode, historicalFiscalYear, historicalStartMonth, historicalEndMonth], async () => {
  currentPage.value = 1
  if (sourceMode.value === 'historical' && selectedEnterpriseId.value) {
    await loadLedgers()
  }
})

watch([activeTab, keyword], () => {
  currentPage.value = 1
})

watch(filteredRows, () => {
  if (currentPage.value > pageCount.value) currentPage.value = pageCount.value
})

function packageEnterpriseId(item) {
  return item?.enterpriseId || item?.enterprise_id || ''
}

function ensureSelection() {
  if (!selectedEnterpriseId.value && enterpriseOptions.value.length) {
    selectedEnterpriseId.value = enterpriseOptions.value[0].id
  }
  const storedPackage = (workspace.workPackages || []).find((item) => item.id === selectedPeriodPackageId.value)
  if (storedPackage) {
    selectedEnterpriseId.value = packageEnterpriseId(storedPackage) || selectedEnterpriseId.value
    return
  }
  const preferred = workspace.selectedPackageId
    ? (workspace.workPackages || []).find((item) => item.id === workspace.selectedPackageId)
    : null
  const next = preferred || periodOptions.value[0] || workspace.workPackages[0]
  if (next) {
    selectedEnterpriseId.value = packageEnterpriseId(next) || selectedEnterpriseId.value
    selectedPeriodPackageId.value = next.id
  }
}

function restoreContext() {
  try {
    const raw =
      typeof window.localStorage?.getItem === 'function'
        ? window.localStorage.getItem(CONTEXT_STORAGE_KEY)
        : '{}'
    const parsed = JSON.parse(raw || '{}')
    selectedEnterpriseId.value = parsed.enterpriseId || ''
    selectedPeriodPackageId.value = parsed.packageId || ''
    sourceMode.value = parsed.sourceMode === 'historical' ? 'historical' : 'monthly'
    historicalFiscalYear.value = parsed.historicalFiscalYear || historicalFiscalYear.value
    historicalStartMonth.value = parsed.historicalStartMonth || 1
    historicalEndMonth.value = parsed.historicalEndMonth || 12
  } catch {
    selectedEnterpriseId.value = ''
    selectedPeriodPackageId.value = ''
    sourceMode.value = 'monthly'
  }
}

function persistContext() {
  if (typeof window.localStorage?.setItem !== 'function') return
  window.localStorage.setItem(
    CONTEXT_STORAGE_KEY,
    JSON.stringify({
      enterpriseId: selectedEnterpriseId.value,
      packageId: selectedPeriodPackageId.value,
      sourceMode: sourceMode.value,
      historicalFiscalYear: historicalFiscalYear.value,
      historicalStartMonth: historicalStartMonth.value,
      historicalEndMonth: historicalEndMonth.value,
    }),
  )
}

function resetLedgerData() {
  summary.value = {
    confirmed_voucher_count: 0,
    pending_voucher_count: 0,
    entry_count: 0,
    is_final: true,
  }
  accountOptions.value = []
  journalRows.value = []
  generalRows.value = []
  detailRows.value = []
  trialBalance.value = {
    rows: [],
    is_balanced: true,
    difference: '0.00',
    opening_debit_total: '0.00',
    opening_credit_total: '0.00',
    period_debit_total: '0.00',
    period_credit_total: '0.00',
    closing_debit_total: '0.00',
    closing_credit_total: '0.00',
  }
}

async function loadLedgers(showSuccess = false) {
  if (!canLoadLedgers()) return
  if (sourceMode.value === 'historical' && Number(historicalStartMonth.value) > Number(historicalEndMonth.value)) {
    ElMessage.warning('起始月份不能晚于截止月份')
    return
  }
  isLoading.value = true
  try {
    const [summaryResponse, accountsResponse, journalResponse, generalResponse, trialResponse] =
      sourceMode.value === 'historical'
        ? await loadHistoricalLedgerResponses()
        : await Promise.all([
            api.ledgers.summary(selectedPeriodPackageId.value),
            api.ledgers.accounts(selectedPeriodPackageId.value),
            api.ledgers.journal(selectedPeriodPackageId.value),
            api.ledgers.general(selectedPeriodPackageId.value),
            api.ledgers.trialBalance(selectedPeriodPackageId.value),
          ])
    summary.value =
      sourceMode.value === 'historical'
        ? {
            confirmed_voucher_count: countHistoricalVouchers(journalResponse.data || []),
            pending_voucher_count: 0,
            entry_count: (journalResponse.data || []).length,
            is_final: true,
          }
        : summaryResponse.data || summary.value
    accountOptions.value = accountsResponse.data || []
    journalRows.value = journalResponse.data || []
    generalRows.value = generalResponse.data || []
    trialBalance.value = trialResponse.data || trialBalance.value
    if (!selectedAccountCode.value && accountOptions.value.length) {
      selectedAccountCode.value = accountOptions.value[0].account_code
    }
    await loadDetailLedger()
    if (showSuccess) ElMessage.success(`账簿已刷新，共 ${summary.value.confirmed_voucher_count || 0} 张凭证`)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '账簿加载失败')
  } finally {
    isLoading.value = false
  }
}

async function loadDetailLedger() {
  if (!canLoadLedgers() || !selectedAccountCode.value) {
    detailRows.value = []
    return
  }
  const response =
    sourceMode.value === 'historical'
      ? await api.historicalImports.detail(selectedEnterpriseId.value, {
          ...historicalParams.value,
          account_code: selectedAccountCode.value,
        })
      : await api.ledgers.detail(selectedPeriodPackageId.value, selectedAccountCode.value)
  detailRows.value = response.data || []
}

function canLoadLedgers() {
  if (sourceMode.value === 'historical') return Boolean(selectedEnterpriseId.value)
  return Boolean(selectedPeriodPackageId.value)
}

function loadHistoricalLedgerResponses() {
  return Promise.all([
    Promise.resolve({ data: null }),
    api.historicalImports.accounts(selectedEnterpriseId.value, historicalParams.value),
    api.historicalImports.journal(selectedEnterpriseId.value, historicalParams.value),
    api.historicalImports.general(selectedEnterpriseId.value, historicalParams.value),
    api.historicalImports.trialBalance(selectedEnterpriseId.value, historicalParams.value),
  ])
}

function countHistoricalVouchers(rows) {
  return new Set(rows.map((row) => `${row.voucher_date}:${row.voucher_number}`)).size
}

function withAccountLabel(row) {
  return {
    ...row,
    account_label: `${row.account_code || ''} ${row.account_name || ''}`.trim(),
  }
}

function withTrialDisplay(row) {
  const displayCode = row.display_code ?? row.account_code ?? ''
  const displayName = row.display_name ?? row.account_name ?? ''
  return {
    ...row,
    display_code: displayCode || '-',
    display_name: row.level ? `　${displayName || '-'}` : displayName || '-',
    account_label: `${row.account_code || ''} ${row.account_name || ''}`.trim(),
  }
}

function rowSearchText(row) {
  return Object.values(row)
    .filter((value) => value !== null && value !== undefined)
    .join(' ')
    .toLowerCase()
}

function displayCell(row, column) {
  if (column.key === 'counter_account_display') return row.counter_account_display || row.counter_accounts || '-'
  const value = row[column.key]
  if (column.amount) return formatAmount(Number(value || 0))
  return value || '-'
}

function rowClass(row) {
  if (row.row_type === 'AUXILIARY') return 'auxiliary-row'
  if (row.is_expandable) return 'account-parent-row'
  return ''
}

function goToPage(page) {
  currentPage.value = Math.min(Math.max(Number(page) || 1, 1), pageCount.value)
}
</script>

<template>
  <section class="ledger-page">
    <div class="panel ledger-panel">
      <header class="panel-header">
        <div>
          <h2>账簿</h2>
          <p>{{ sourceMode === 'historical' ? '查询已导入历史账套的序时账、总账、明细账与余额表。' : '基于已确认凭证生成序时账、总账、明细账与余额表。' }}</p>
        </div>
        <el-button :loading="isLoading" @click="() => loadLedgers(true)">刷新</el-button>
      </header>

      <div class="mode-toggle" aria-label="账簿来源">
        <button type="button" :class="{ active: sourceMode === 'monthly' }" @click="sourceMode = 'monthly'">月度工作包</button>
        <button type="button" :class="{ active: sourceMode === 'historical' }" @click="sourceMode = 'historical'">历史账套</button>
      </div>

      <div class="context-bar">
        <label class="field">
          <span>企业主体</span>
          <el-select v-model="selectedEnterpriseId" placeholder="企业主体">
            <el-option
              v-for="enterprise in enterpriseOptions"
              :key="enterprise.id"
              :label="enterprise.name"
              :value="enterprise.id"
            />
          </el-select>
        </label>
        <label v-if="sourceMode === 'monthly'" class="field">
          <span>工作期间</span>
          <el-select v-model="selectedPeriodPackageId" placeholder="工作期间">
            <el-option
              v-for="item in periodOptions"
              :key="item.id"
              :label="item.period"
              :value="item.id"
            />
          </el-select>
        </label>
        <label v-if="sourceMode === 'historical'" class="field">
          <span>会计年度</span>
          <el-input v-model="historicalFiscalYear" placeholder="会计年度" />
        </label>
        <label v-if="sourceMode === 'historical'" class="field">
          <span>起始月份</span>
          <el-select v-model="historicalStartMonth" placeholder="起始月份">
            <el-option v-for="month in monthOptions" :key="month.value" :label="month.label" :value="month.value" />
          </el-select>
        </label>
        <label v-if="sourceMode === 'historical'" class="field">
          <span>截止月份</span>
          <el-select v-model="historicalEndMonth" placeholder="截止月份">
            <el-option v-for="month in monthOptions" :key="month.value" :label="month.label" :value="month.value" />
          </el-select>
        </label>
      </div>

      <div class="summary-grid">
        <div class="summary-card">
          <span>{{ sourceMode === 'historical' ? '历史凭证' : '已确认凭证' }}</span>
          <strong>{{ summary.confirmed_voucher_count }}</strong>
        </div>
        <div class="summary-card">
          <span>凭证分录</span>
          <strong>{{ summary.entry_count }}</strong>
        </div>
        <div class="summary-card" :class="{ warning: summary.pending_voucher_count }">
          <span>未确认凭证</span>
          <strong>{{ summary.pending_voucher_count }}</strong>
        </div>
        <div class="summary-card" :class="{ warning: !trialBalance.is_balanced }">
          <span>借贷平衡</span>
          <strong>{{ trialBalance.is_balanced ? '平衡' : formatAmount(Number(trialBalance.difference || 0)) }}</strong>
        </div>
      </div>

      <el-alert
        v-if="summary.pending_voucher_count"
        type="warning"
        :closable="false"
        :title="`仍有 ${summary.pending_voucher_count} 张凭证未确认，账簿只包含已确认凭证。`"
      />

      <el-tabs v-model="activeTab">
        <el-tab-pane v-for="tab in tabOptions" :key="tab.name" :label="tab.label" :name="tab.name" />
      </el-tabs>

      <div class="toolbar">
        <el-input v-model="keyword" placeholder="搜索日期、凭证号、摘要、科目" clearable />
        <el-select
          v-if="activeTab === 'detail'"
          v-model="selectedAccountCode"
          placeholder="选择明细科目"
          class="account-select"
        >
          <el-option
            v-for="account in accountOptions"
            :key="account.account_code"
            :label="`${account.account_code} ${account.account_name}`"
            :value="account.account_code"
          />
        </el-select>
      </div>

      <div v-if="activeTab === 'detail'" class="active-account">
        当前明细科目：{{ activeAccountLabel }} · {{ selectedPeriodLabel }}
      </div>

      <div class="ledger-table-scroll">
        <table class="ledger-table">
          <thead>
            <tr>
              <th
                v-for="column in currentColumns"
                :key="column.key"
                :style="{ width: column.width, minWidth: column.minWidth, textAlign: column.align || 'left' }"
              >
                {{ column.label }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in pagedRows"
              :key="row.voucher_entry_id || `${row.row_type || 'row'}:${row.parent_account_code || ''}:${row.account_code}:${row.auxiliary_name || ''}`"
              :class="rowClass(row)"
            >
              <td
                v-for="column in currentColumns"
                :key="column.key"
                :class="{ amount: column.amount }"
                :style="{ textAlign: column.align || 'left' }"
              >
                {{ displayCell(row, column) }}
              </td>
            </tr>
            <tr v-if="!pagedRows.length">
              <td class="empty-cell" :colspan="currentColumns.length">暂无账簿数据</td>
            </tr>
          </tbody>
        </table>
      </div>

      <footer class="table-footer">
        <span>{{ paginationSummary }}</span>
        <span>第 {{ currentPage }} / {{ pageCount }} 页</span>
        <el-pagination
          v-model:current-page="currentPage"
          layout="prev, pager, next"
          :page-size="pageSize"
          :total="filteredRows.length"
          @update:current-page="goToPage"
        />
      </footer>
    </div>
  </section>
</template>

<style scoped>
.ledger-page {
  padding: 24px;
}

.panel {
  border: 1px solid #d8e2f0;
  border-radius: 8px;
  background: #fff;
}

.ledger-panel {
  padding: 18px;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.panel-header h2 {
  margin: 0;
  color: #17233c;
  font-size: 20px;
}

.panel-header p {
  margin: 6px 0 0;
  color: #63738a;
}

.context-bar {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) repeat(3, minmax(140px, 180px));
  gap: 14px;
  padding: 14px;
  margin-bottom: 14px;
  border: 1px solid #dbe5f2;
  border-radius: 6px;
  background: #f6f9fc;
}

.mode-toggle {
  display: inline-flex;
  padding: 3px;
  margin-bottom: 12px;
  border: 1px solid #d8e2f0;
  border-radius: 6px;
  background: #f6f9fc;
}

.mode-toggle button {
  min-width: 96px;
  height: 30px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #52657c;
  cursor: pointer;
}

.mode-toggle button.active {
  background: #fff;
  color: #1f6feb;
  box-shadow: 0 1px 3px rgb(15 23 42 / 12%);
}

.field {
  display: grid;
  gap: 6px;
  color: #52657c;
  font-size: 13px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.summary-card {
  padding: 14px;
  border: 1px solid #dbe5f2;
  border-radius: 6px;
  background: #f8fbff;
}

.summary-card span {
  display: block;
  color: #63738a;
  font-size: 13px;
}

.summary-card strong {
  display: block;
  margin-top: 6px;
  color: #17233c;
  font-size: 22px;
}

.summary-card.warning strong {
  color: #d97706;
}

.toolbar {
  display: flex;
  gap: 10px;
  margin: 14px 0 10px;
}

.account-select {
  width: 260px;
  flex: 0 0 auto;
}

.active-account {
  margin-bottom: 8px;
  color: #52657c;
  font-size: 13px;
}

.ledger-table-scroll {
  width: 100%;
  overflow-x: auto;
  border: 1px solid #dbe5f2;
  border-radius: 6px;
}

.ledger-table {
  width: 100%;
  min-width: 980px;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 13px;
}

.ledger-table th {
  padding: 10px 12px;
  color: #334762;
  font-weight: 600;
  background: #eef3f8;
  border-bottom: 1px solid #dbe5f2;
}

.ledger-table td {
  padding: 10px 12px;
  color: #24344d;
  border-bottom: 1px solid #e8edf4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ledger-table tbody tr:nth-child(even) {
  background: #fafbfd;
}

.ledger-table tbody tr.account-parent-row {
  background: #eaf5ff;
  font-weight: 600;
}

.ledger-table tbody tr.auxiliary-row {
  background: #fbfdff;
}

.ledger-table tbody tr.auxiliary-row td:first-child {
  color: #6b7b91;
}

.ledger-table .amount {
  font-variant-numeric: tabular-nums;
}

.empty-cell {
  text-align: center;
  color: #8a98aa;
}

.table-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
  color: #52657c;
  font-size: 13px;
}

@media (max-width: 1100px) {
  .context-bar,
  .summary-grid {
    grid-template-columns: 1fr;
  }

  .toolbar {
    flex-direction: column;
  }

  .account-select {
    width: 100%;
  }
}
</style>
