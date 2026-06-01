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

      <InvoiceLedgerTable :rows="filteredRows" :loading="isLoading" />
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

watch(
  () => activePackage.value?.id,
  () => {
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
