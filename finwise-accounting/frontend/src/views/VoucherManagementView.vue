<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'
import { formatAmount } from '../components/source-ledgers/ledgerFormatters'

const CONTEXT_STORAGE_KEY = 'finwise:voucher-management:context'

const workspace = useWorkspaceStore()
const selectedEnterpriseId = ref('')
const selectedPeriodPackageId = ref('')
const currentFiscalYear = new Date().getFullYear()
const historicalFiscalYear = ref(currentFiscalYear)
const historicalStartMonth = ref(1)
const historicalEndMonth = ref(12)
const keyword = ref('')
const vouchers = ref([])
const isLoading = ref(false)
const selectedVoucherId = ref('')
const currentPage = ref(1)
const pageSize = 20

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
  return { value, label: `${String(value).padStart(2, '0')}月` }
})
const yearOptions = Array.from({ length: 10 }, (_, index) => currentFiscalYear + 1 - index).map((year) => ({
  value: year,
  label: `${year}`,
}))
const historicalParams = computed(() => ({
  fiscal_year: Number(historicalFiscalYear.value),
  period_start_month: Number(historicalStartMonth.value),
  period_end_month: Number(historicalEndMonth.value),
}))
const selectedContextLabel = computed(() => {
  const startMonth = Number(historicalStartMonth.value)
  const endMonth = Number(historicalEndMonth.value)
  if (startMonth === endMonth) return `${historicalFiscalYear.value}-${String(startMonth).padStart(2, '0')}`
  return `${historicalFiscalYear.value} 年 ${startMonth} 月至 ${endMonth} 月`
})
const voucherCountLabel = computed(() => '凭证')
const selectedEnterpriseName = computed(() => {
  return enterpriseOptions.value.find((enterprise) => enterprise.id === selectedEnterpriseId.value)?.name || '当前企业'
})
const selectedMonthlyPackage = computed(() => {
  const fiscalYear = Number(historicalFiscalYear.value)
  const startMonth = Number(historicalStartMonth.value)
  const endMonth = Number(historicalEndMonth.value)
  if (!fiscalYear || startMonth !== endMonth) return null
  return (
    periodOptions.value.find((item) => {
      const period = parsePeriod(item.period)
      return period.year === fiscalYear && period.month === startMonth
    }) || null
  )
})
const selectedVoucher = computed(() => vouchers.value.find((item) => voucherRowId(item) === selectedVoucherId.value) || null)
const voucherRows = computed(() =>
  vouchers.value.map((voucher) => ({
    ...voucher,
    rowId: voucherRowId(voucher),
    counterparty: voucherCounterparty(voucher),
    debitTotal: entryTotal(voucher, 'DEBIT'),
    creditTotal: entryTotal(voucher, 'CREDIT'),
    sourceType: sourceTypeLabel(voucher),
    maker: voucher.confirmed_by || (voucher.__source === 'historical' ? '历史导入' : '-'),
  })),
)
const pageCount = computed(() => Math.max(1, Math.ceil(voucherRows.value.length / pageSize)))
const paginatedVoucherRows = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return voucherRows.value.slice(start, start + pageSize)
})
const hasVoucherRows = computed(() => voucherRows.value.length > 0)
const emptyStateTitle = computed(() => {
  if (keyword.value.trim()) return '没有找到匹配的凭证'
  return '当前期间暂无可展示凭证'
})
const emptyStateDescription = computed(() => {
  if (keyword.value.trim()) return '请调整搜索关键词，或清空搜索后查看当前期间的全部凭证。'
  return '请确认该企业和期间已经完成凭证确认，或切换企业、年度、月份范围后重新查看。'
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
  const current = activePackage.value
  if (!current || packageEnterpriseId(current) !== selectedEnterpriseId.value) {
    selectedPeriodPackageId.value = periodOptions.value[0]?.id || ''
    syncHistoricalPeriodFromPackage(selectedPeriodPackageId.value)
  }
  loadConfirmedVouchers()
})

watch([historicalFiscalYear, historicalStartMonth, historicalEndMonth], async () => {
  selectedPeriodPackageId.value = selectedMonthlyPackage.value?.id || ''
  persistContext()
  if (selectedEnterpriseId.value) {
    await loadConfirmedVouchers()
  }
})

function packageEnterpriseId(item) {
  return item?.enterpriseId || item?.enterprise_id || ''
}

function parsePeriod(period) {
  const matched = String(period || '').match(/^(\d{4})-(\d{1,2})$/)
  if (!matched) return { year: null, month: null }
  return { year: Number(matched[1]), month: Number(matched[2]) }
}

function syncHistoricalPeriodFromPackage(packageId) {
  if (!packageId) return
  const period = parsePeriod((workspace.workPackages || []).find((item) => item.id === packageId)?.period)
  if (!period.year || !period.month) return
  historicalFiscalYear.value = period.year
  historicalStartMonth.value = period.month
  historicalEndMonth.value = period.month
}

function ensureSelection() {
  if (!selectedEnterpriseId.value && enterpriseOptions.value.length) {
    selectedEnterpriseId.value = enterpriseOptions.value[0].id
  }
  const storedPackage = (workspace.workPackages || []).find((item) => item.id === selectedPeriodPackageId.value)
  if (storedPackage) {
    selectedEnterpriseId.value = packageEnterpriseId(storedPackage) || selectedEnterpriseId.value
    syncHistoricalPeriodFromPackage(storedPackage.id)
    return
  }
  const preferred = workspace.selectedPackageId
    ? (workspace.workPackages || []).find((item) => item.id === workspace.selectedPackageId)
    : null
  const next = preferred || periodOptions.value[0] || workspace.workPackages[0]
  if (next) {
    selectedEnterpriseId.value = packageEnterpriseId(next) || selectedEnterpriseId.value
    selectedPeriodPackageId.value = next.id
    syncHistoricalPeriodFromPackage(next.id)
  }
}

function restoreContext() {
  try {
    const parsed = JSON.parse(window.localStorage?.getItem(CONTEXT_STORAGE_KEY) || '{}')
    selectedEnterpriseId.value = parsed.enterpriseId || ''
    selectedPeriodPackageId.value = parsed.packageId || ''
    historicalFiscalYear.value = Number(parsed.historicalFiscalYear) || historicalFiscalYear.value
    historicalStartMonth.value = parsed.historicalStartMonth || 1
    historicalEndMonth.value = parsed.historicalEndMonth || 12
  } catch {
    selectedEnterpriseId.value = ''
    selectedPeriodPackageId.value = ''
  }
}

function persistContext() {
  window.localStorage?.setItem(
    CONTEXT_STORAGE_KEY,
    JSON.stringify({
      enterpriseId: selectedEnterpriseId.value,
      packageId: selectedPeriodPackageId.value,
      historicalFiscalYear: historicalFiscalYear.value,
      historicalStartMonth: historicalStartMonth.value,
      historicalEndMonth: historicalEndMonth.value,
    }),
  )
}

async function loadConfirmedVouchers() {
  if (!selectedEnterpriseId.value) return
  if (Number(historicalStartMonth.value) > Number(historicalEndMonth.value)) {
    ElMessage.warning('起始月份不能晚于截止月份')
    return
  }
  isLoading.value = true
  try {
    const searchText = keyword.value.trim()
    const results = await Promise.all([loadMonthlyConfirmedVouchers(searchText), loadHistoricalConfirmedVouchers(searchText)])
    vouchers.value = results.flat()
    if (selectedVoucherId.value && !vouchers.value.some((voucher) => voucherRowId(voucher) === selectedVoucherId.value)) {
      selectedVoucherId.value = ''
    }
    currentPage.value = 1
    if (!selectedVoucherId.value && vouchers.value.length) {
      selectedVoucherId.value = voucherRowId(vouchers.value[0])
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '已确认凭证加载失败')
  } finally {
    isLoading.value = false
  }
}

async function loadMonthlyConfirmedVouchers(searchText) {
  const monthlyPackageId = selectedMonthlyPackage.value?.id
  if (!monthlyPackageId) return []
  const params = { status: 'CONFIRMED' }
  if (searchText) params.keyword = searchText
  const response = await api.vouchers.list(monthlyPackageId, params)
  return (response.data || [])
    .filter((voucher) => voucher.status === 'CONFIRMED')
    .map((voucher) => ({ ...voucher, __source: 'monthly' }))
}

async function loadHistoricalConfirmedVouchers(searchText) {
  const response = await api.historicalImports.vouchers(selectedEnterpriseId.value, {
    ...historicalParams.value,
    keyword: searchText || undefined,
  })
  return (response.data || []).map((voucher) => ({ ...voucher, __source: 'historical' }))
}

function searchVouchers() {
  return loadConfirmedVouchers()
}

function clearKeywordAndReload() {
  keyword.value = ''
  return loadConfirmedVouchers()
}

function openVoucherDetail(voucher) {
  selectedVoucherId.value = voucherRowId(voucher)
}

function goToPage(page) {
  currentPage.value = Math.min(Math.max(page, 1), pageCount.value)
}

function entryTotal(voucher, direction) {
  return (voucher?.entries || [])
    .filter((entry) => entry.direction === direction)
    .reduce((sum, entry) => sum + Number(entry.amount || 0), 0)
}

function voucherCounterparty(voucher) {
  const source = voucher?.source_data || voucher?.sourceData || {}
  const bank = source.bank_transaction || source.bankTransaction || source.bank_transactions?.[0] || source.bankTransactions?.[0]
  const invoice = source.invoice || source.invoices?.[0]
  if (bank?.counterparty_name) return bank.counterparty_name
  if (invoice?.counterparty_name) return invoice.counterparty_name
  if (invoice?.invoice_direction === 'OUTPUT') return invoice.buyer_name || source.counterparty_name || '-'
  if (invoice?.invoice_direction === 'INPUT') return invoice.seller_name || source.counterparty_name || '-'
  return source.counterparty_name || '-'
}

function sourceTypeLabel(voucher) {
  if (voucher?.__source === 'historical' || voucher?.source_data?.source_type === 'HISTORICAL_LEDGER') return '历史导入'
  const source = voucher?.source_data || voucher?.sourceData || {}
  const hasBank = Boolean(source.bank_transaction || source.bank_transactions?.length || source.bankTransaction || source.bankTransactions?.length)
  const hasInvoice = Boolean(source.invoice || source.invoices?.length)
  if (hasBank && hasInvoice) return '流水+发票'
  if (hasBank) return '银行流水'
  if (hasInvoice) return '发票'
  return '手工凭证'
}

function formatDateTime(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 16)
}

function entryDebit(entry) {
  return entry.direction === 'DEBIT' ? Number(entry.amount || 0) : 0
}

function entryCredit(entry) {
  return entry.direction === 'CREDIT' ? Number(entry.amount || 0) : 0
}

function voucherNumberText(voucher) {
  return voucher.voucher_number || '未编号'
}

function entryKey(voucher, entry, index) {
  return entry.id || `${voucherRowId(voucher)}:${entry.line_no || index}`
}

function voucherRowId(voucher) {
  return `${voucher?.__source || 'monthly'}:${voucher?.id || ''}`
}
</script>

<template>
  <section class="voucher-management-page">
    <header class="voucher-toolbar">
      <div class="voucher-search">
        <el-input v-model="keyword" clearable placeholder="可输入凭证号/摘要/科目/金额..." @clear="searchVouchers" @keyup.enter="searchVouchers" />
        <button class="icon-search-button" type="button" aria-label="搜索凭证" :disabled="isLoading" @click="searchVouchers">⌕</button>
      </div>
      <div class="toolbar-spacer" />
      <button class="text-action" type="button" :disabled="isLoading" @click="loadConfirmedVouchers">刷新</button>
    </header>

    <section class="voucher-filter-strip">
      <label>
        <span>企业主体</span>
        <el-select v-model="selectedEnterpriseId" placeholder="企业主体" filterable>
          <el-option v-for="enterprise in enterpriseOptions" :key="enterprise.id" :label="enterprise.name" :value="enterprise.id" />
        </el-select>
      </label>
      <label>
        <span>会计年度</span>
        <el-select v-model="historicalFiscalYear" placeholder="会计年度">
          <el-option v-for="year in yearOptions" :key="year.value" :label="year.label" :value="year.value" />
        </el-select>
      </label>
      <label>
        <span>起始月份</span>
        <el-select v-model="historicalStartMonth" placeholder="起始月份">
          <el-option v-for="month in monthOptions" :key="month.value" :label="month.label" :value="month.value" />
        </el-select>
      </label>
      <label>
        <span>截止月份</span>
        <el-select v-model="historicalEndMonth" placeholder="截止月份">
          <el-option v-for="month in monthOptions" :key="month.value" :label="month.label" :value="month.value" />
        </el-select>
      </label>
      <div class="list-summary" data-testid="voucher-count-summary">
        <span>{{ voucherCountLabel }}：</span>
        <strong data-testid="voucher-count">{{ voucherRows.length }}</strong>
        <span> 张 · {{ selectedContextLabel }}</span>
      </div>
    </section>

    <section v-if="!hasVoucherRows" class="voucher-empty-state" data-testid="voucher-empty-state">
      <div class="empty-state-mark">凭</div>
      <div class="empty-state-content">
        <p class="empty-state-kicker">{{ selectedEnterpriseName }} · {{ selectedContextLabel }}</p>
        <h2>{{ emptyStateTitle }}</h2>
        <p>{{ emptyStateDescription }}</p>
        <dl>
          <div>
            <dt>当前筛选</dt>
            <dd>{{ keyword.trim() || '未输入关键词' }}</dd>
          </div>
          <div>
            <dt>{{ voucherCountLabel }}</dt>
            <dd>{{ voucherRows.length }} 张</dd>
          </div>
        </dl>
      </div>
      <div class="empty-state-actions">
        <button v-if="keyword.trim()" class="pager-button" type="button" :disabled="isLoading" @click="clearKeywordAndReload">清空搜索</button>
        <button class="pager-button primary-empty-action" type="button" :disabled="isLoading" @click="loadConfirmedVouchers">刷新</button>
      </div>
    </section>

    <div v-else class="voucher-ledger-layout">
      <div class="voucher-ledger-scroll">
        <table class="voucher-ledger-table">
          <thead>
            <tr>
              <th>摘要</th>
              <th>科目</th>
              <th>借方金额</th>
              <th>贷方金额</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="voucher in paginatedVoucherRows" :key="voucher.rowId">
              <tr class="voucher-meta-row" :class="{ selected: selectedVoucherId === voucher.rowId }">
                <td colspan="4">
                  <button class="voucher-number-link" type="button" @click="openVoucherDetail(voucher)">
                    日期：{{ voucher.voucher_date }}
                  </button>
                  <span>制单人：{{ voucher.maker }}</span>
                  <span>凭证字号：{{ voucherNumberText(voucher) }}</span>
                  <span>附单据 {{ voucher.attachment_count || 0 }} 张</span>
                  <span v-if="voucher.counterparty !== '-'">对方：{{ voucher.counterparty }}</span>
                  <span>{{ voucher.sourceType }}</span>
                  <span v-if="voucher.confirmed_at">确认：{{ formatDateTime(voucher.confirmed_at) }}</span>
                </td>
              </tr>
              <tr v-for="(entry, index) in voucher.entries" :key="entryKey(voucher, entry, index)" class="voucher-entry-row">
                <td class="summary-cell" :title="voucher.summary">{{ voucher.summary || '-' }}</td>
                <td class="subject-cell">
                  <span class="subject-code">{{ entry.account_code }}</span>
                  {{ entry.account_name }}
                </td>
                <td class="amount">{{ entryDebit(entry) ? formatAmount(entryDebit(entry)) : '' }}</td>
                <td class="amount">{{ entryCredit(entry) ? formatAmount(entryCredit(entry)) : '' }}</td>
              </tr>
              <tr class="voucher-total-row">
                <td colspan="2"><span class="total-icon">总</span>合计</td>
                <td class="amount">{{ formatAmount(voucher.debitTotal) }}</td>
                <td class="amount">{{ formatAmount(voucher.creditTotal) }}</td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

    </div>

    <div v-if="hasVoucherRows" class="pagination-bar" aria-label="凭证分页">
      <span>每页 {{ pageSize }} 张凭证</span>
      <span>第 {{ currentPage }} / {{ pageCount }} 页</span>
      <button class="pager-button previous-page-button" type="button" :disabled="currentPage <= 1" @click="goToPage(currentPage - 1)">
        上一页
      </button>
      <button class="pager-button next-page-button" type="button" :disabled="currentPage >= pageCount" @click="goToPage(currentPage + 1)">
        下一页
      </button>
    </div>
  </section>
</template>

<style scoped>
.voucher-management-page {
  display: grid;
  align-content: start;
  gap: 10px;
  min-height: calc(100vh - 96px);
  background: #f5f7fb;
}

.voucher-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 48px;
  padding: 8px 12px;
  border-bottom: 1px solid #dfe4ef;
  background: #fff;
}

.voucher-search {
  display: flex;
  align-items: center;
  width: min(360px, 34vw);
  border-bottom: 1px solid #e4e9f2;
}

.voucher-search :deep(.el-input__wrapper) {
  box-shadow: none;
  padding-left: 0;
}

.icon-search-button {
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #5b45e5;
  cursor: pointer;
}

.text-action {
  height: 32px;
  border: 0;
  background: transparent;
  color: #2f3a4c;
  cursor: pointer;
  white-space: nowrap;
}

.toolbar-spacer {
  flex: 1;
}

.voucher-filter-strip {
  display: grid;
  grid-template-columns:
    minmax(280px, 1.7fr)
    minmax(130px, 0.6fr)
    minmax(110px, 0.5fr)
    minmax(110px, 0.5fr)
    minmax(110px, 0.5fr)
    minmax(220px, auto);
  gap: 12px;
  align-items: end;
  padding: 10px 12px;
  border: 1px solid #e1e7f0;
  border-radius: 6px;
  background: #fff;
}

.voucher-filter-strip label {
  display: grid;
  gap: 4px;
  color: #66758c;
  font-size: 12px;
}

.voucher-filter-strip :deep(.el-select),
.voucher-filter-strip :deep(.el-input) {
  width: 100%;
}

.voucher-filter-strip :deep(.el-select__wrapper),
.voucher-filter-strip :deep(.el-input__wrapper) {
  min-height: 32px;
}

.list-summary {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid #d9e8ff;
  border-radius: 4px;
  background: #f7fbff;
  color: #66758c;
  white-space: nowrap;
}

.list-summary strong {
  color: #1f2d3d;
  font-size: 18px;
}

.voucher-ledger-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
  min-height: 0;
}

.voucher-empty-state {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) max-content;
  gap: 22px;
  align-items: center;
  min-height: 360px;
  padding: 36px;
  border: 1px solid #dbe2ec;
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgb(47 122 247 / 7%), transparent 48%),
    #fff;
  box-shadow: 0 1px 2px rgb(20 31 52 / 4%);
}

.empty-state-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  border: 1px solid #b9d5ff;
  border-radius: 16px;
  background: #eef6ff;
  color: #1f73e8;
  font-size: 28px;
  font-weight: 800;
}

.empty-state-content {
  display: grid;
  gap: 10px;
}

.empty-state-kicker {
  margin: 0;
  color: #66758c;
  font-size: 13px;
}

.empty-state-content h2 {
  margin: 0;
  color: #172033;
  font-size: 22px;
  line-height: 1.35;
}

.empty-state-content p {
  max-width: 720px;
  margin: 0;
  color: #4c5d73;
  line-height: 1.7;
}

.empty-state-content dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(140px, 1fr));
  gap: 10px;
  max-width: 760px;
  margin: 10px 0 0;
}

.empty-state-content dl div {
  min-width: 0;
  padding: 12px;
  border: 1px solid #e2e8f2;
  border-radius: 6px;
  background: #f8fbff;
}

.empty-state-content dt {
  color: #77859a;
  font-size: 12px;
}

.empty-state-content dd {
  overflow: hidden;
  margin: 4px 0 0;
  color: #1f2d3d;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-state-actions {
  display: flex;
  gap: 10px;
  align-self: end;
}

.primary-empty-action {
  border-color: #2f7af7;
  background: #2f7af7;
  color: #fff;
}

.voucher-ledger-scroll {
  max-height: calc(100vh - 250px);
  overflow-x: auto;
  overflow-y: auto;
  border: 1px solid #dbe2ec;
  background: #fff;
}

.voucher-ledger-table {
  width: 100%;
  min-width: 1060px;
  border-collapse: collapse;
  table-layout: fixed;
  color: #263243;
  font-size: 14px;
}

.voucher-ledger-table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  height: 34px;
  padding: 0 12px;
  border-right: 1px solid #d7deea;
  border-bottom: 1px solid #d7deea;
  background: #e9ecf6;
  color: #1f2d3d;
  text-align: center;
  font-weight: 700;
}

.voucher-ledger-table th:nth-child(1),
.voucher-ledger-table td:nth-child(1) {
  width: 280px;
}

.voucher-ledger-table th:nth-child(2),
.voucher-ledger-table td:nth-child(2) {
  width: 390px;
}

.voucher-ledger-table th:nth-child(3),
.voucher-ledger-table td:nth-child(3),
.voucher-ledger-table th:nth-child(4),
.voucher-ledger-table td:nth-child(4) {
  width: 220px;
}

.voucher-ledger-table td {
  height: 34px;
  padding: 0 12px;
  border-right: 1px solid #dfe5ee;
  border-bottom: 1px solid #dfe5ee;
  background: #fff;
  vertical-align: middle;
}

.voucher-meta-row td {
  height: 38px;
  background: #fff;
  color: #2f3a4c;
}

.voucher-meta-row.selected td {
  background: #f7f5ff;
}

.voucher-meta-row span,
.voucher-meta-row button {
  margin-right: 34px;
}

.voucher-number-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: #263243;
  font: inherit;
  cursor: pointer;
}

.voucher-number-link:hover {
  color: #5946e8;
  text-decoration: underline;
}

.summary-cell,
.subject-cell {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subject-code {
  margin-right: 6px;
  color: #39465a;
}

.voucher-total-row td {
  height: 42px;
  background: #f0fbfc;
  color: #1d2c37;
  font-weight: 700;
}

.total-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  margin-right: 8px;
  border-radius: 3px;
  background: #6db4ff;
  color: #fff;
  font-size: 12px;
}

.pager-button {
  min-width: 68px;
  height: 30px;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius-sm);
  background: #fff;
  color: var(--fw-text);
  cursor: pointer;
}

.pager-button:disabled {
  color: var(--fw-muted);
  background: #f3f6fa;
  cursor: not-allowed;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  color: #66758c;
}

.amount {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 1080px) {
  .voucher-toolbar {
    flex-wrap: wrap;
  }

  .voucher-search {
    width: 100%;
  }

  .voucher-filter-strip,
  .voucher-ledger-layout {
    grid-template-columns: 1fr;
  }

  .voucher-empty-state {
    grid-template-columns: 1fr;
    min-height: 320px;
  }

  .empty-state-actions {
    align-self: auto;
  }

  .empty-state-content dl {
    grid-template-columns: 1fr;
  }
}
</style>
