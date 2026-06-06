// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import BankLedgerTable from '../components/source-ledgers/BankLedgerTable.vue'
import {
  bankCounterpartyLabel,
  bankDirectionClass,
  bankDirectionLabel,
  sourceProcessingStatusTag,
} from '../components/source-ledgers/ledgerFormatters'

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
    expect(bankComponent).toContain('source_processing_status_label')
    expect(bankComponent).toContain('来源处理')
    expect(bankComponent).toContain('voucher_status_label')
    expect(bankViewSource).toContain('refreshBankLedger')
  })

  it('paginates the independent bank ledger page at 20 rows and reports filtered counts', () => {
    const bankViewSource = readFileSync(resolve(__dirname, 'BankLedgerView.vue'), 'utf8')
    expect(bankViewSource).toContain('const ledgerPageSize = 20')
    expect(bankViewSource).toContain('const currentPage = ref(1)')
    expect(bankViewSource).toContain('const pagedRows = computed')
    expect(bankViewSource).toContain(':rows="pagedRows"')
    expect(bankViewSource).toContain('当前显示 ${pagedRows.value.length} 条 / 筛选结果 ${filteredRows.value.length} 条 / 原始总数 ${bankRows.value.length} 条')
    expect(bankViewSource).toContain('<el-pagination')
    expect(bankViewSource).toContain('v-model:current-page="currentPage"')
    expect(bankViewSource).toContain(':page-size="ledgerPageSize"')
    expect(bankViewSource).toContain(':total="filteredRows.length"')
    expect(bankViewSource).toContain('watch(keyword')
    expect(bankViewSource).toContain('currentPage.value = 1')
  })

  it('puts voucher number first and keeps bank ledger summary compact', () => {
    const bankComponent = readFileSync(resolve(root, 'components/source-ledgers/BankLedgerTable.vue'), 'utf8')
    expect(bankComponent.indexOf('label="凭证号"')).toBeLessThan(bankComponent.indexOf('label="日期"'))
    expect(bankComponent.indexOf('label="日期"')).toBeLessThan(bankComponent.indexOf('label="交易对方"'))
    expect(bankComponent.indexOf('label="交易对方"')).toBeLessThan(bankComponent.indexOf('label="收支方向"'))
    expect(bankComponent.indexOf('label="收支方向"')).toBeLessThan(bankComponent.indexOf('label="摘要"'))
    expect(bankComponent).toContain('label="交易对方" width="390"')
    expect(bankComponent).toContain('bankCounterpartyLabel(row)')
    expect(bankComponent).not.toContain('prop="counterparty_name" label="交易对方" min-width')
    expect(bankComponent).toContain('prop="summary" label="摘要" min-width="120"')
    expect(bankComponent).not.toContain('prop="summary" label="摘要" width="120"')
    expect(bankComponent).toContain('bank-direction-tag')
    expect(bankComponent).toContain('bankDirectionLabel(row)')
    expect(bankDirectionLabel({ credit_amount: '100.00', debit_amount: '0.00' })).toBe('收款')
    expect(bankDirectionLabel({ credit_amount: '0.00', debit_amount: '100.00' })).toBe('付款')
    expect(bankDirectionClass({ credit_amount: '100.00', debit_amount: '0.00' })).toBe('is-receipt')
    expect(bankDirectionClass({ credit_amount: '0.00', debit_amount: '100.00' })).toBe('is-payment')
  })

  it('labels bank fee rows without pretending a real counterparty exists', () => {
    expect(bankCounterpartyLabel({ counterparty_name: '苏州客户有限公司', summary: '电子汇入' })).toBe('苏州客户有限公司')
    expect(bankCounterpartyLabel({ counterparty_name: '', summary: '收费', remark: '电子商业汇票-系统使用费' })).toBe('银行收费')
    expect(bankCounterpartyLabel({ counterparty_name: '', summary: '电子转账' })).toBe('对方户名缺失')
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

  it('paginates the independent invoice ledger page at 20 rows and reports filtered counts', () => {
    const invoiceViewSource = readFileSync(resolve(__dirname, 'InvoiceLedgerView.vue'), 'utf8')
    expect(invoiceViewSource).toContain('const ledgerPageSize = 20')
    expect(invoiceViewSource).toContain('const currentPage = ref(1)')
    expect(invoiceViewSource).toContain('const pagedRows = computed')
    expect(invoiceViewSource).toContain(':rows="pagedRows"')
    expect(invoiceViewSource).toContain('当前显示 ${pagedRows.value.length} 张 / 筛选结果 ${filteredRows.value.length} 张 / 原始总数 ${invoiceRows.value.length} 张')
    expect(invoiceViewSource).toContain('<el-pagination')
    expect(invoiceViewSource).toContain('v-model:current-page="currentPage"')
    expect(invoiceViewSource).toContain(':page-size="ledgerPageSize"')
    expect(invoiceViewSource).toContain(':total="filteredRows.length"')
    expect(invoiceViewSource).toContain('watch([keyword, directionFilter]')
    expect(invoiceViewSource).toContain('currentPage.value = 1')
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

  it('keeps single-sided source rows in the warning attention state', () => {
    expect(sourceProcessingStatusTag('SINGLE_SIDED')).toBe('warning')
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
      source_processing_status: 'UNPROCESSED',
      source_processing_status_label: '未处理',
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
