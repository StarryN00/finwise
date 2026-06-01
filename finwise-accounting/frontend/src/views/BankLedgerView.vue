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

      <div class="ledger-table-scroll">
        <el-table
          v-loading="isLoading"
          :data="filteredRows"
          class="ledger-table"
          stripe
          empty-text="暂无资金流水"
        >
          <el-table-column prop="transaction_date" label="日期" width="112" />
          <el-table-column prop="summary" label="摘要" min-width="180" show-overflow-tooltip />
          <el-table-column prop="direction_label" label="收支方向" width="104" />
          <el-table-column prop="counterparty_name" label="交易对方" min-width="190" show-overflow-tooltip />
          <el-table-column label="收入金额" width="130" align="right">
            <template #default="{ row }">{{ formatAmount(row.credit_amount) }}</template>
          </el-table-column>
          <el-table-column label="支出金额" width="130" align="right">
            <template #default="{ row }">{{ formatAmount(row.debit_amount) }}</template>
          </el-table-column>
          <el-table-column label="余额" width="130" align="right">
            <template #default="{ row }">{{ row.balance == null ? '-' : formatAmount(row.balance) }}</template>
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
          <el-table-column prop="linked_invoice_count" label="关联发票" width="96" align="right" />
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
const bankRows = ref([])
const keyword = ref('')
const isLoading = ref(false)
const activePackage = computed(() => workspace.activePackage)
const processedCount = computed(() => bankRows.value.filter((row) => row.voucher_status !== 'UNPROCESSED').length)
const filteredRows = computed(() => {
  const text = keyword.value.trim()
  if (!text) return bankRows.value
  return bankRows.value.filter((row) =>
    [
      row.transaction_date,
      row.summary,
      row.direction_label,
      row.counterparty_name,
      row.transaction_amount,
      row.matching_status_label,
      row.voucher_status_label,
    ]
      .join(' ')
      .includes(text),
  )
})

watch(
  () => activePackage.value?.id,
  () => {
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
  min-width: 1420px;
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
