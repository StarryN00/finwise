<template>
  <section class="source-ledger-page">
    <PackageContextBar
      status-label="资金处理进度"
      :status-value="`${processedCount}/${bankRows.length} 条`"
    />

    <div class="ledger-card">
      <div class="ledger-header">
        <div>
          <h2 class="section-title">资金流水</h2>
          <p class="caption">银行流水原始台账，按匹配状态和凭证状态跟踪处理进度。</p>
        </div>
        <div class="ledger-actions">
          <el-input
            v-model="keyword"
            class="ledger-search"
            clearable
            placeholder="搜索日期、摘要、对方、金额"
          />
          <el-button :loading="isLoading" @click="refreshBankLedger">刷新</el-button>
        </div>
      </div>

      <BankLedgerTable :rows="pagedRows" :loading="isLoading" />
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
import BankLedgerTable from '../components/source-ledgers/BankLedgerTable.vue'
import { sourceRowMatchesKeyword } from '../components/source-ledgers/ledgerFormatters'
import { api } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const bankRows = ref([])
const keyword = ref('')
const isLoading = ref(false)
const ledgerPageSize = 20
const currentPage = ref(1)
const activePackage = computed(() => workspace.activePackage)
const processedCount = computed(() => bankRows.value.filter((row) => row.voucher_status !== 'UNPROCESSED').length)
const filteredRows = computed(() => {
  const text = keyword.value.trim()
  if (!text) return bankRows.value
  return bankRows.value.filter((row) =>
    sourceRowMatchesKeyword(row, text, [
      'transaction_date',
      'summary',
      'direction_label',
      'counterparty_name',
      'transaction_amount',
      'matching_status_label',
      'voucher_status_label',
    ]),
  )
})
const pagedRows = computed(() => {
  const start = (currentPage.value - 1) * ledgerPageSize
  return filteredRows.value.slice(start, start + ledgerPageSize)
})
const paginationSummary = computed(
  () =>
    `当前显示 ${pagedRows.value.length} 条 / 筛选结果 ${filteredRows.value.length} 条 / 原始总数 ${bankRows.value.length} 条`,
)

watch(keyword, () => {
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
    refreshBankLedger()
  },
)

onMounted(async () => {
  if (!workspace.workPackages.length) {
    await workspace.loadWorkspace()
  }
  await refreshBankLedger()
})

async function refreshBankLedger() {
  const packageId = activePackage.value?.id
  if (!packageId) return
  isLoading.value = true
  try {
    const response = await api.sourceLedgers.bank(packageId)
    bankRows.value = response.data
    ElMessage.success(`资金流水已刷新，共 ${response.data.length} 条`)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '资金流水加载失败')
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

  .ledger-search {
    width: 100%;
  }
}
</style>
