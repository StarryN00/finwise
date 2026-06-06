<template>
  <div class="ledger-table-scroll">
    <el-table
      v-loading="loading"
      :data="rows"
      class="ledger-table bank-ledger-table"
      stripe
      highlight-current-row
      empty-text="暂无资金流水"
      @row-click="emit('row-select', $event)"
    >
      <el-table-column label="凭证号" width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ row.linked_vouchers ? linkedVoucherLabel(row) : '-' }}</template>
      </el-table-column>
      <el-table-column prop="transaction_date" label="日期" width="112" />
      <el-table-column label="交易对方" width="390" show-overflow-tooltip>
        <template #default="{ row }">{{ bankCounterpartyLabel(row) }}</template>
      </el-table-column>
      <el-table-column label="收支方向" width="104">
        <template #default="{ row }">
          <span class="bank-direction-tag" :class="bankDirectionClass(row)">{{ bankDirectionLabel(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="summary" label="摘要" min-width="120" show-overflow-tooltip />
      <el-table-column label="收入金额" width="130" align="right">
        <template #default="{ row }">{{ formatAmount(row.credit_amount) }}</template>
      </el-table-column>
      <el-table-column label="支出金额" width="130" align="right">
        <template #default="{ row }">{{ formatAmount(row.debit_amount) }}</template>
      </el-table-column>
      <el-table-column label="余额" width="130" align="right">
        <template #default="{ row }">{{ row.balance == null ? '-' : formatAmount(row.balance) }}</template>
      </el-table-column>
      <el-table-column label="来源处理" width="118">
        <template #default="{ row }">
          <el-tag :type="sourceProcessingStatusTag(row.source_processing_status)" size="small">
            {{ row.source_processing_status_label || sourceProcessingStatusLabel(row) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="凭证状态" width="118">
        <template #default="{ row }">
          <el-tag :type="voucherStatusTag(row.voucher_status)" size="small">{{ row.voucher_status_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="linked_invoice_count" label="关联发票" width="96" align="right" />
    </el-table>
  </div>
</template>

<script setup>
import {
  bankCounterpartyLabel,
  bankDirectionClass,
  bankDirectionLabel,
  formatAmount,
  linkedVoucherLabel,
  sourceProcessingStatusLabel,
  sourceProcessingStatusTag,
  voucherStatusTag,
} from './ledgerFormatters'

defineProps({
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['row-select'])
</script>

<style scoped>
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

.bank-direction-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  min-height: 22px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.bank-direction-tag.is-receipt {
  border: 1px solid #bbf7d0;
  background: #dcfce7;
  color: #166534;
}

.bank-direction-tag.is-payment {
  border: 1px solid #fed7aa;
  background: #ffedd5;
  color: #9a3412;
}

.bank-direction-tag.is-neutral {
  border: 1px solid #cbd5e1;
  background: #f1f5f9;
  color: #475569;
}
</style>
