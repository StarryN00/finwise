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
