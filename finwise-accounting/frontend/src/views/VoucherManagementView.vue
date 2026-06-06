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
const keyword = ref('')
const vouchers = ref([])
const isLoading = ref(false)
const detailVisible = ref(false)
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
const selectedVoucher = computed(() => vouchers.value.find((item) => item.id === selectedVoucherId.value) || null)
const voucherRows = computed(() =>
  vouchers.value.map((voucher) => ({
    ...voucher,
    counterparty: voucherCounterparty(voucher),
    debitTotal: entryTotal(voucher, 'DEBIT'),
    creditTotal: entryTotal(voucher, 'CREDIT'),
    sourceType: sourceTypeLabel(voucher),
  })),
)
const pageCount = computed(() => Math.max(1, Math.ceil(voucherRows.value.length / pageSize)))
const paginatedVoucherRows = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return voucherRows.value.slice(start, start + pageSize)
})
const selectedVoucherNumber = computed(() => {
  const value = selectedVoucher.value?.voucher_number || '未编号'
  return value.replace(/^记-?/, '')
})
const selectedVoucherTotal = computed(() => Math.max(entryTotal(selectedVoucher.value, 'DEBIT'), entryTotal(selectedVoucher.value, 'CREDIT')))
const selectedVoucherUpperTotal = computed(() => amountToChineseUpper(selectedVoucherTotal.value))

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
  if (current && packageEnterpriseId(current) === selectedEnterpriseId.value) return
  selectedPeriodPackageId.value = periodOptions.value[0]?.id || ''
})

watch(selectedPeriodPackageId, async (packageId) => {
  persistContext()
  if (packageId) {
    await loadConfirmedVouchers()
  } else {
    vouchers.value = []
  }
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
    const parsed = JSON.parse(window.localStorage?.getItem(CONTEXT_STORAGE_KEY) || '{}')
    selectedEnterpriseId.value = parsed.enterpriseId || ''
    selectedPeriodPackageId.value = parsed.packageId || ''
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
    }),
  )
}

async function loadConfirmedVouchers() {
  if (!selectedPeriodPackageId.value) return
  isLoading.value = true
  try {
    const params = { status: 'CONFIRMED' }
    const searchText = keyword.value.trim()
    if (searchText) params.keyword = searchText
    const response = await api.vouchers.list(selectedPeriodPackageId.value, params)
    vouchers.value = (response.data || []).filter((voucher) => voucher.status === 'CONFIRMED')
    if (selectedVoucherId.value && !vouchers.value.some((voucher) => voucher.id === selectedVoucherId.value)) {
      selectedVoucherId.value = ''
    }
    currentPage.value = 1
    if (!selectedVoucherId.value && vouchers.value.length) {
      selectedVoucherId.value = vouchers.value[0].id
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '已确认凭证加载失败')
  } finally {
    isLoading.value = false
  }
}

function searchVouchers() {
  return loadConfirmedVouchers()
}

function openVoucherDetail(voucher) {
  selectedVoucherId.value = voucher.id
  detailVisible.value = true
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

function amountToChineseUpper(value) {
  const amount = Math.round(Number(value || 0) * 100)
  if (!amount) return '零元整'
  const integer = Math.floor(amount / 100)
  const cent = amount % 100
  const fraction = ['角', '分']
  const digits = ['零', '壹', '贰', '叁', '肆', '伍', '陆', '柒', '捌', '玖']
  const units = ['', '拾', '佰', '仟']
  const bigUnits = ['', '万', '亿']
  const parts = []
  let remaining = integer
  let groupIndex = 0
  while (remaining > 0) {
    const group = remaining % 10000
    if (group) {
      parts.unshift(`${fourDigitToUpper(group, digits, units)}${bigUnits[groupIndex]}`)
    }
    remaining = Math.floor(remaining / 10000)
    groupIndex += 1
  }
  const integerText = `${parts.join('')}元`
  if (cent === 0) return `${integerText}整`
  const jiao = Math.floor(cent / 10)
  const fen = cent % 10
  return `${integerText}${jiao ? `${digits[jiao]}${fraction[0]}` : ''}${fen ? `${digits[fen]}${fraction[1]}` : ''}`
}

function fourDigitToUpper(value, digits, units) {
  const chars = String(value).padStart(4, '0').split('').map(Number)
  let output = ''
  let zeroPending = false
  chars.forEach((digit, index) => {
    const unitIndex = 3 - index
    if (!digit) {
      zeroPending = Boolean(output)
      return
    }
    if (zeroPending) {
      output += '零'
      zeroPending = false
    }
    output += `${digits[digit]}${units[unitIndex]}`
  })
  return output
}
</script>

<template>
  <section class="panel voucher-management-page">
    <div class="panel-header">
      <div>
        <h2>凭证管理</h2>
        <p class="muted">查看已确认凭证，按主体、期间和关键词快速检索。</p>
      </div>
      <el-button :loading="isLoading" @click="loadConfirmedVouchers">刷新</el-button>
    </div>

    <div class="context-grid">
      <label>
        <span>企业主体</span>
        <el-select v-model="selectedEnterpriseId" placeholder="企业主体" filterable>
          <el-option v-for="enterprise in enterpriseOptions" :key="enterprise.id" :label="enterprise.name" :value="enterprise.id" />
        </el-select>
      </label>
      <label>
        <span>工作期间</span>
        <el-select v-model="selectedPeriodPackageId" placeholder="工作期间">
          <el-option v-for="item in periodOptions" :key="item.id" :label="item.period" :value="item.id" />
        </el-select>
      </label>
      <label class="search-field">
        <span>搜索</span>
        <div class="search-row">
          <el-input v-model="keyword" placeholder="搜索凭证号、摘要、对方主体、科目" @keyup.enter="searchVouchers" />
          <el-button class="search-button" type="primary" :loading="isLoading" @click="searchVouchers">搜索</el-button>
        </div>
      </label>
    </div>

    <div class="list-summary">
      <strong>显示 {{ voucherRows.length }} 张已确认凭证</strong>
      <span>{{ activePackage?.company || '未选择企业' }} · {{ activePackage?.period || '-' }}</span>
    </div>

    <div class="voucher-table-wrap">
      <table class="voucher-table">
        <thead>
          <tr>
            <th>凭证日期</th>
            <th>凭证号</th>
            <th>摘要</th>
            <th>对方主体</th>
            <th>借方合计</th>
            <th>贷方合计</th>
            <th>来源类型</th>
            <th>确认时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="voucher in paginatedVoucherRows" :key="voucher.id">
            <td>{{ voucher.voucher_date }}</td>
            <td>
              <button class="voucher-number-link" type="button" @click="openVoucherDetail(voucher)">
                {{ voucher.voucher_number || '未编号' }}
              </button>
            </td>
            <td class="cell-ellipsis" :title="voucher.summary">{{ voucher.summary }}</td>
            <td class="cell-ellipsis" :title="voucher.counterparty">{{ voucher.counterparty }}</td>
            <td class="amount">{{ formatAmount(voucher.debitTotal) }}</td>
            <td class="amount">{{ formatAmount(voucher.creditTotal) }}</td>
            <td>{{ voucher.sourceType }}</td>
            <td>{{ formatDateTime(voucher.confirmed_at) }}</td>
            <td>
              <el-button class="view-voucher-button" type="primary" size="small" @click="openVoucherDetail(voucher)">查看详情</el-button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="pagination-bar" aria-label="凭证分页">
      <span>每页 {{ pageSize }} 条</span>
      <span>第 {{ currentPage }} / {{ pageCount }} 页</span>
      <button class="pager-button previous-page-button" type="button" :disabled="currentPage <= 1" @click="goToPage(currentPage - 1)">
        上一页
      </button>
      <button class="pager-button next-page-button" type="button" :disabled="currentPage >= pageCount" @click="goToPage(currentPage + 1)">
        下一页
      </button>
    </div>

    <el-dialog v-model="detailVisible" width="1120px" class="accounting-voucher-dialog" title="记账凭证">
      <section v-if="selectedVoucher" class="accounting-voucher">
        <h2>记账凭证</h2>
        <div class="voucher-slip-meta">
          <span>记 字第 {{ selectedVoucherNumber }} 号</span>
          <span>日期：{{ selectedVoucher.voucher_date }}</span>
          <span>附件 {{ selectedVoucher.attachment_count || 0 }} 张</span>
        </div>
        <table class="voucher-slip-table">
          <thead>
            <tr>
              <th class="col-index">序号</th>
              <th>摘要</th>
              <th>会计科目</th>
              <th>借方金额</th>
              <th>贷方金额</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in selectedVoucher.entries" :key="entry.line_no">
              <td class="col-index">{{ entry.line_no }}</td>
              <td>{{ selectedVoucher.summary }}</td>
              <td>
                <strong>{{ entry.account_code }}</strong>
                {{ entry.account_name }}
              </td>
              <td class="digit-amount">{{ entry.direction === 'DEBIT' ? formatAmount(entry.amount) : '' }}</td>
              <td class="digit-amount">{{ entry.direction === 'CREDIT' ? formatAmount(entry.amount) : '' }}</td>
            </tr>
            <tr class="total-row">
              <td colspan="3">合计：{{ selectedVoucherUpperTotal }}</td>
              <td class="digit-amount">{{ formatAmount(selectedVoucherTotal) }}</td>
              <td class="digit-amount">{{ formatAmount(selectedVoucherTotal) }}</td>
            </tr>
          </tbody>
        </table>
        <div class="voucher-slip-footer">
          <span>制单人：{{ selectedVoucher.confirmed_by || '-' }}</span>
          <span>审核人：-</span>
          <span>修改人：-</span>
        </div>
      </section>
    </el-dialog>
  </section>
</template>

<style scoped>
.voucher-management-page {
  display: grid;
  gap: 16px;
}

.panel-header,
.search-row,
.list-summary,
.voucher-slip-meta,
.voucher-slip-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.panel-header h2,
.accounting-voucher h2 {
  margin: 0;
}

.muted {
  margin: 4px 0 0;
  color: var(--fw-muted);
}

.context-grid {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 180px minmax(360px, 2fr);
  gap: 12px;
  align-items: end;
}

.context-grid label {
  display: grid;
  gap: 6px;
  color: var(--fw-text);
  font-weight: 600;
}

.search-row {
  align-items: stretch;
}

.search-row .el-input {
  flex: 1;
}

.list-summary {
  justify-content: flex-start;
  color: var(--fw-muted);
}

.list-summary strong {
  color: var(--fw-text);
}

.voucher-table-wrap {
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius-sm);
}

.voucher-table {
  width: 100%;
  min-width: 1180px;
  border-collapse: collapse;
  table-layout: fixed;
}

.voucher-table th,
.voucher-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--fw-line);
  text-align: left;
  white-space: nowrap;
}

.voucher-table th {
  background: #eef3f9;
  color: #30415c;
  font-weight: 700;
}

.voucher-table th:nth-child(1),
.voucher-table td:nth-child(1) {
  width: 110px;
}

.voucher-table th:nth-child(2),
.voucher-table td:nth-child(2) {
  width: 110px;
}

.voucher-table th:nth-child(3),
.voucher-table td:nth-child(3) {
  width: 150px;
}

.voucher-table th:nth-child(4),
.voucher-table td:nth-child(4) {
  width: 240px;
}

.voucher-table th:nth-child(5),
.voucher-table td:nth-child(5),
.voucher-table th:nth-child(6),
.voucher-table td:nth-child(6) {
  width: 120px;
}

.voucher-table th:nth-child(7),
.voucher-table td:nth-child(7) {
  width: 100px;
}

.voucher-table th:nth-child(8),
.voucher-table td:nth-child(8) {
  width: 150px;
}

.voucher-table th:nth-child(9),
.voucher-table td:nth-child(9) {
  width: 120px;
}

.voucher-number-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--fw-primary);
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

.voucher-number-link:hover {
  text-decoration: underline;
}

.cell-ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  color: var(--fw-muted);
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

.amount,
.digit-amount {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.accounting-voucher {
  padding: 8px 4px 4px;
}

.accounting-voucher h2 {
  margin-bottom: 18px;
  text-align: center;
  font-size: 22px;
  font-weight: 500;
}

.voucher-slip-meta {
  padding: 0 36px 12px;
  border-bottom: 1px solid #c7cbd3;
  color: #303846;
}

.voucher-slip-table {
  width: 100%;
  margin-top: 14px;
  border-collapse: collapse;
  table-layout: fixed;
}

.voucher-slip-table th {
  padding: 10px 8px;
  border: 1px solid #23a9b8;
  color: #fff;
  background: #37bfd0;
  text-align: center;
  font-size: 15px;
}

.voucher-slip-table td {
  height: 58px;
  padding: 10px 12px;
  border: 1px solid #c7cbd3;
  vertical-align: top;
}

.voucher-slip-table .col-index {
  width: 56px;
  text-align: center;
}

.voucher-slip-table th:nth-child(2),
.voucher-slip-table td:nth-child(2) {
  width: 190px;
}

.voucher-slip-table th:nth-child(3),
.voucher-slip-table td:nth-child(3) {
  width: 360px;
}

.digit-amount {
  width: 190px;
  font-family: 'Courier New', monospace;
  font-size: 22px;
  letter-spacing: 4px;
  vertical-align: middle;
}

.total-row td {
  height: 54px;
  font-weight: 700;
  vertical-align: middle;
}

.voucher-slip-footer {
  justify-content: flex-start;
  gap: 100px;
  padding: 14px 4px 2px;
  color: #7d8796;
}

@media (max-width: 1080px) {
  .context-grid {
    grid-template-columns: 1fr;
  }
}
</style>
