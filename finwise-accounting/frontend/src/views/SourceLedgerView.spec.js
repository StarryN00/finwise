// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import BankLedgerTable from '../components/source-ledgers/BankLedgerTable.vue'
import { matchingStatusTag } from '../components/source-ledgers/ledgerFormatters'

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

  it('keeps unmatched ledger rows in the warning attention state', () => {
    expect(matchingStatusTag('UNMATCHED')).toBe('warning')
  })

  it('emits row-select with the ledger row payload when a bank row is selected', async () => {
    const ledgerRow = {
      id: 'bank-row-1',
      transaction_date: '2026-04-08',
      summary: '收到客户货款',
      direction_label: '收入',
      counterparty_name: '客户A',
      credit_amount: '1130.00',
      debit_amount: '0',
      balance: null,
      matching_status: 'UNMATCHED',
      matching_status_label: '未匹配',
      voucher_status: 'UNPROCESSED',
      voucher_status_label: '未处理',
      linked_invoice_count: 0,
      linked_vouchers: [{ id: 'voucher-1', voucher_number: '记-001' }],
    }
    const wrapper = mount(BankLedgerTable, {
      props: {
        rows: [ledgerRow],
      },
      global: {
        directives: {
          loading: {},
        },
        stubs: {
          ElTable: {
            props: ['data'],
            template: '<button type="button" @click="$emit(`row-click`, data[0])">select row</button>',
          },
          ElTableColumn: true,
          ElTag: { template: '<span><slot /></span>' },
        },
      },
    })

    await wrapper.find('button').trigger('click')

    expect(wrapper.emitted('row-select')?.[0]?.[0]).toStrictEqual(ledgerRow)
    expect(wrapper.emitted('row-select')?.[0]?.[0]).not.toHaveProperty('target')
  })
})
