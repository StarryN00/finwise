import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(__dirname, '..')
const clientSource = readFileSync(resolve(root, 'api/client.js'), 'utf8')
const routerSource = readFileSync(resolve(root, 'router/index.js'), 'utf8')
const layoutSource = readFileSync(resolve(root, 'components/AppLayout.vue'), 'utf8')

describe('source ledger views', () => {
  it('wires source ledger API methods and routes', () => {
    expect(clientSource).toContain('sourceLedgers')
    expect(clientSource).toContain('/monthly-packages/${packageId}/bank-ledger')
    expect(clientSource).toContain('/monthly-packages/${packageId}/invoice-ledger')
    expect(clientSource).toContain('/monthly-packages/${packageId}/voucher-ledger-summary')
    expect(routerSource).toContain('/bank-ledger')
    expect(routerSource).toContain('/invoice-ledger')
    expect(layoutSource).toContain('资金流水')
    expect(layoutSource).toContain('发票台账')
  })

  it('keeps bank ledger table usable and Chinese-labeled', () => {
    const bankViewSource = readFileSync(resolve(__dirname, 'BankLedgerView.vue'), 'utf8')
    const bankComponent = readFileSync(resolve(root, 'components/source-ledgers/BankLedgerTable.vue'), 'utf8')
    expect(bankViewSource).toContain('资金流水')
    expect(bankViewSource).toContain('<BankLedgerTable')
    expect(bankComponent).toContain('ledger-table-scroll')
    expect(bankComponent).toContain('交易对方')
    expect(bankComponent).toContain('收支方向')
    expect(bankComponent).toContain('matching_status_label')
    expect(bankComponent).toContain('voucher_status_label')
    expect(bankViewSource).toContain('refreshBankLedger')
  })

  it('keeps invoice ledger table usable and counterparty-focused', () => {
    const invoiceViewSource = readFileSync(resolve(__dirname, 'InvoiceLedgerView.vue'), 'utf8')
    const invoiceComponent = readFileSync(resolve(root, 'components/source-ledgers/InvoiceLedgerTable.vue'), 'utf8')
    expect(invoiceViewSource).toContain('发票台账')
    expect(invoiceViewSource).toContain('<InvoiceLedgerTable')
    expect(invoiceComponent).toContain('ledger-table-scroll')
    expect(invoiceComponent).toContain('发票方向')
    expect(invoiceComponent).toContain('对方名称')
    expect(invoiceComponent).toContain('counterparty_role')
    expect(invoiceComponent).toContain('invoice_direction_label')
    expect(invoiceViewSource).toContain('refreshInvoiceLedger')
  })

  it('uses reusable source ledger components that emit row selection for voucher workbench reuse', () => {
    const bankComponent = readFileSync(resolve(root, 'components/source-ledgers/BankLedgerTable.vue'), 'utf8')
    const invoiceComponent = readFileSync(resolve(root, 'components/source-ledgers/InvoiceLedgerTable.vue'), 'utf8')
    expect(bankComponent).toContain("defineEmits(['row-select'])")
    expect(invoiceComponent).toContain("defineEmits(['row-select'])")
    expect(bankComponent).toContain('linked_vouchers')
    expect(invoiceComponent).toContain('linked_vouchers')
    expect(bankComponent).toContain('凭证号')
    expect(invoiceComponent).toContain('凭证号')
  })
})
