export function formatAmount(value) {
  const number = Number(value || 0)
  return number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function voucherStatusTag(status) {
  if (status === 'CONFIRMED') return 'success'
  if (status === 'PENDING_CONFIRMATION') return 'warning'
  if (status === 'REJECTED') return 'danger'
  return 'info'
}

export function matchingStatusTag(status) {
  if (status === 'MATCHED') return 'success'
  if (status === 'UNMATCHED') return 'warning'
  if (status === 'PARTIAL') return 'warning'
  return 'info'
}

export function sourceProcessingStatusTag(status) {
  if (status === 'PAIRED') return 'success'
  if (status === 'DIFFERENCE_FILLED') return 'warning'
  if (status === 'SINGLE_SIDED') return 'warning'
  if (status === 'NEEDS_REVIEW') return 'danger'
  return 'info'
}

export function sourceProcessingStatusLabel(row) {
  return row?.source_processing_status_label || row?.matching_status_label || '未处理'
}

export function bankDirectionLabel(row) {
  const credit = Number(row?.credit_amount || 0)
  const debit = Number(row?.debit_amount || 0)
  if (credit > 0 && debit <= 0) return '收款'
  if (debit > 0 && credit <= 0) return '付款'
  return '其他'
}

export function bankDirectionClass(row) {
  const label = bankDirectionLabel(row)
  if (label === '收款') return 'is-receipt'
  if (label === '付款') return 'is-payment'
  return 'is-neutral'
}

export function bankCounterpartyLabel(row) {
  const counterparty = String(row?.counterparty_name || '').trim()
  if (counterparty) return counterparty

  const context = [row?.summary, row?.remark, row?.note].filter(Boolean).join(' ')
  if (/收费|手续费|短信服务费|账户服务费|账户管理费|系统使用费|对公资金划转/.test(context)) {
    return '银行收费'
  }
  if (/缴税|扣税|税款|税费|电子税务局|国库/.test(context)) {
    return '税务扣款'
  }
  return '对方户名缺失'
}

export function linkedVoucherLabel(row) {
  const links = row?.linked_vouchers || []
  if (!links.length) return '-'
  return links.map((item) => item.voucher_number || '未编号').join('、')
}

export function sourceRowMatchesKeyword(row, keyword, fields) {
  const text = String(keyword || '').trim()
  if (!text) return true
  return fields.map((field) => row?.[field] ?? '').join(' ').includes(text)
}

export function sourceRowMatchesFilter(row, field, value) {
  if (!value || value === 'all') return true
  return row?.[field] === value
}
