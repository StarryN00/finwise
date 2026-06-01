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

      <div class="ledger-table-scroll">
        <el-table
          v-loading="isLoading"
          :data="filteredRows"
          class="ledger-table"
          stripe
          empty-text="暂无发票"
        >
          <el-table-column prop="invoice_direction_label" label="发票方向" width="104" />
          <el-table-column prop="invoice_number" label="发票号码" min-width="180" show-overflow-tooltip />
          <el-table-column prop="invoice_date" label="开票日期" width="112" />
          <el-table-column prop="counterparty_role" label="对方角色" width="96" />
          <el-table-column prop="counterparty_name" label="对方名称" min-width="190" show-overflow-tooltip />
          <el-table-column label="金额" width="130" align="right">
            <template #default="{ row }">{{ formatAmount(row.amount) }}</template>
          </el-table-column>
          <el-table-column label="税额" width="130" align="right">
            <template #default="{ row }">{{ formatAmount(row.tax_amount) }}</template>
          </el-table-column>
          <el-table-column label="价税合计" width="130" align="right">
            <template #default="{ row }">{{ formatAmount(row.total_amount) }}</template>
          </el-table-column>
          <el-table-column label="匹配状态" width="112">
            <template #default="{ row }">
              <el-tag :type="row.matching_status === 'MATCHED' ? 'success' : 'warning'" size="small">
                {{ row.matching_status_label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="凭证状态" width="112">
            <template #default="{ row }">
              <el-tag :type="voucherStatusTag(row.voucher_status)" size="small">
                {{ row.voucher_status_label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="linked_bank_count" label="关联流水" width="96" align="right" />
          <el-table-column label="凭证号" width="120" show-overflow-tooltip>
            <template #default="{ row }">{{ row.linked_voucher_numbers?.join('、') || '-' }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import PackageContextBar from '../components/PackageContextBar.vue'
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
    if (!text) return true
    return [
      row.invoice_direction_label,
      row.invoice_number,
      row.invoice_date,
      row.counterparty_role,
      row.counterparty_name,
      row.total_amount,
      row.matching_status_label,
      row.voucher_status_label,
    ]
      .join(' ')
      .includes(text)
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

function formatAmount(value) {
  const number = Number(value || 0)
  return number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function voucherStatusTag(status) {
  if (status === 'CONFIRMED') return 'success'
  if (status === 'PENDING_CONFIRMATION') return 'warning'
  return 'info'
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

.ledger-table-scroll {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  scrollbar-color: var(--fw-brand) #eaf2ff;
  scrollbar-width: thin;
}

.ledger-table-scroll::-webkit-scrollbar {
  height: 12px;
}

.ledger-table-scroll::-webkit-scrollbar-track {
  background: #eaf2ff;
}

.ledger-table-scroll::-webkit-scrollbar-thumb {
  border: 2px solid #eaf2ff;
  border-radius: 999px;
  background: var(--fw-brand);
}

.ledger-table {
  width: 100%;
  min-width: 1500px;
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
