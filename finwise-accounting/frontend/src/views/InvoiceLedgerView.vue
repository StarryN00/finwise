<template>
  <section class="source-ledger-page">
    <PackageContextBar
      status-label="发票处理进度"
      :status-value="`${processedCount}/${invoiceRows.length} 张`"
    />

    <div class="ledger-card">
      <div class="ledger-header">
        <div>
          <h2 class="section-title">发票台账</h2>
          <p class="caption">进项和销项发票原始台账，按对方主体、匹配状态和凭证状态跟踪。</p>
        </div>
        <div class="ledger-actions">
          <el-select v-model="directionFilter" class="direction-filter" placeholder="发票方向">
            <el-option label="全部发票" value="all" />
            <el-option label="进项发票" value="INPUT" />
            <el-option label="销项发票" value="OUTPUT" />
          </el-select>
          <el-input
            v-model="keyword"
            class="ledger-search"
            clearable
            placeholder="搜索发票号、对方、金额"
          />
          <el-button :loading="isLoading" @click="refreshInvoiceLedger">刷新</el-button>
        </div>
      </div>

      <InvoiceLedgerTable :rows="pagedRows" :loading="isLoading" />
      <div class="ledger-pagination-bar">
        <span class="ledger-count">{{ paginationSummary }}</span>
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="ledgerPageSize"
          :total="filteredRows.length"
          background
          layout="prev, pager, next"
          small
        />
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import PackageContextBar from '../components/PackageContextBar.vue'
import InvoiceLedgerTable from '../components/source-ledgers/InvoiceLedgerTable.vue'
import { sourceRowMatchesKeyword } from '../components/source-ledgers/ledgerFormatters'
import { api } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const invoiceRows = ref([])
const keyword = ref('')
const directionFilter = ref('all')
const isLoading = ref(false)
const ledgerPageSize = 20
const currentPage = ref(1)
const activePackage = computed(() => workspace.activePackage)
const processedCount = computed(() => invoiceRows.value.filter((row) => row.voucher_status !== 'UNPROCESSED').length)
const filteredRows = computed(() => {
  const text = keyword.value.trim()
  return invoiceRows.value.filter((row) => {
    const directionMatched = directionFilter.value === 'all' || row.invoice_direction === directionFilter.value
    if (!directionMatched) return false
    return sourceRowMatchesKeyword(row, text, [
      'invoice_direction_label',
      'invoice_number',
      'invoice_date',
      'counterparty_role',
      'counterparty_name',
      'total_amount',
      'matching_status_label',
      'voucher_status_label',
    ])
  })
})
const pagedRows = computed(() => {
  const start = (currentPage.value - 1) * ledgerPageSize
  return filteredRows.value.slice(start, start + ledgerPageSize)
})
const paginationSummary = computed(
  () =>
    `当前显示 ${pagedRows.value.length} 张 / 筛选结果 ${filteredRows.value.length} 张 / 原始总数 ${invoiceRows.value.length} 张`,
)

watch([keyword, directionFilter], () => {
  currentPage.value = 1
})

watch(
  () => filteredRows.value.length,
  () => {
    clampCurrentPage()
  },
)

watch(
  () => activePackage.value?.id,
  () => {
    currentPage.value = 1
    refreshInvoiceLedger()
  },
)

onMounted(async () => {
  if (!workspace.workPackages.length) {
    await workspace.loadWorkspace()
  }
  await refreshInvoiceLedger()
})

async function refreshInvoiceLedger() {
  const packageId = activePackage.value?.id
  if (!packageId) return
  isLoading.value = true
  try {
    const response = await api.sourceLedgers.invoices(packageId)
    invoiceRows.value = response.data
    ElMessage.success(`发票台账已刷新，共 ${response.data.length} 张`)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '发票台账加载失败')
  } finally {
    isLoading.value = false
  }
}

function clampCurrentPage() {
  const maxPage = Math.max(1, Math.ceil(filteredRows.value.length / ledgerPageSize))
  if (currentPage.value > maxPage) {
    currentPage.value = maxPage
  }
}
</script>

<style scoped>
.source-ledger-page {
  display: grid;
  gap: 16px;
}

.ledger-card {
  border: 1px solid var(--fw-line);
  border-radius: var(--fw-radius);
  background: var(--fw-surface);
  overflow: hidden;
}

.ledger-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
  border-bottom: 1px solid var(--fw-line);
}

.ledger-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

.direction-filter {
  width: 132px;
}

.ledger-search {
  width: 280px;
}

.ledger-pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px 16px;
  border-top: 1px solid var(--fw-line);
  flex-wrap: wrap;
}

.ledger-count {
  color: var(--fw-muted);
  font-size: 13px;
}

@media (max-width: 760px) {
  .ledger-header {
    display: grid;
  }

  .ledger-search,
  .direction-filter {
    width: 100%;
  }
}
</style>
