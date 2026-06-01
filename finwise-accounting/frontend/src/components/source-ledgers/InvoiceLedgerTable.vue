<template>
  <div class="ledger-table-scroll">
    <el-table
      v-loading="loading"
      :data="rows"
      class="ledger-table invoice-ledger-table"
      stripe
      highlight-current-row
      empty-text="暂无发票"
      @row-click="emit('row-select', $event)"
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
      <el-table-column label="匹配状态" width="118">
        <template #default="{ row }">
          <el-tag :type="matchingStatusTag(row.matching_status)" size="small">{{ row.matching_status_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="凭证状态" width="118">
        <template #default="{ row }">
          <el-tag :type="voucherStatusTag(row.voucher_status)" size="small">{{ row.voucher_status_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="linked_bank_count" label="关联流水" width="96" align="right" />
      <el-table-column label="凭证号" width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ row.linked_vouchers ? linkedVoucherLabel(row) : '-' }}</template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { formatAmount, linkedVoucherLabel, matchingStatusTag, voucherStatusTag } from './ledgerFormatters'

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
  min-width: 1500px;
}
</style>
