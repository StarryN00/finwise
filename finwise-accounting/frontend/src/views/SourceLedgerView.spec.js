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
    expect(bankViewSource).toContain('资金流水')
    expect(bankViewSource).toContain('ledger-table-scroll')
    expect(bankViewSource).toContain('交易对方')
    expect(bankViewSource).toContain('收支方向')
    expect(bankViewSource).toContain('matching_status_label')
    expect(bankViewSource).toContain('voucher_status_label')
    expect(bankViewSource).toContain('refreshBankLedger')
  })

  it('keeps invoice ledger table usable and counterparty-focused', () => {
    const invoiceViewSource = readFileSync(resolve(__dirname, 'InvoiceLedgerView.vue'), 'utf8')
    expect(invoiceViewSource).toContain('发票台账')
    expect(invoiceViewSource).toContain('ledger-table-scroll')
    expect(invoiceViewSource).toContain('发票方向')
    expect(invoiceViewSource).toContain('对方名称')
    expect(invoiceViewSource).toContain('counterparty_role')
    expect(invoiceViewSource).toContain('invoice_direction_label')
    expect(invoiceViewSource).toContain('refreshInvoiceLedger')
  })
})
