// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import VoucherWorkbenchView from './VoucherWorkbenchView.vue'
import BankLedgerTable from '../components/source-ledgers/BankLedgerTable.vue'
import InvoiceLedgerTable from '../components/source-ledgers/InvoiceLedgerTable.vue'
import { api } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'

vi.mock('element-plus', () => ({
  ElMessage: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}))

vi.mock('../api/client', () => ({
  api: {
    sourceLedgers: {
      bank: vi.fn(),
      invoices: vi.fn(),
      summary: vi.fn(),
    },
    vouchers: {
      list: vi.fn(),
      preprocess: vi.fn(),
      confirm: vi.fn(),
      reject: vi.fn(),
      reopen: vi.fn(),
      rematchCandidates: vi.fn(),
      rematch: vi.fn(),
      adjustTreatment: vi.fn(),
    },
    workspace: {
      snapshot: vi.fn(),
    },
  },
}))

const __dirname = dirname(fileURLToPath(import.meta.url))
const viewSource = readFileSync(resolve(__dirname, 'VoucherWorkbenchView.vue'), 'utf8')
const clientSource = readFileSync(resolve(__dirname, '../api/client.js'), 'utf8')
const routerSource = readFileSync(resolve(__dirname, '../router/index.js'), 'utf8')

describe('VoucherWorkbenchView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.vouchers.list.mockResolvedValue({ data: [] })
    api.sourceLedgers.summary.mockResolvedValue({ data: {} })
    api.sourceLedgers.bank.mockResolvedValue({ data: [] })
    api.sourceLedgers.invoices.mockResolvedValue({ data: [] })
    api.workspace.snapshot.mockImplementation((packageId) =>
      Promise.resolve({
        data: {
          workPackages: workPackages(),
          selectedPackageId: packageId || 'package-1',
        },
      }),
    )
  })

  it('wires the voucher workbench page, API client, and route', () => {
    expect(viewSource).toContain('凭证生成工作台')
    expect(viewSource).toContain('AI 预处理')
    expect(viewSource).toContain('当前操作主体')
    expect(viewSource).toContain('选择企业主体')
    expect(viewSource).toContain('选择工作期间')
    expect(viewSource).toContain('selectedEnterpriseId')
    expect(viewSource).toContain('selectedPeriodPackageId')
    expect(viewSource).toContain('enterpriseOptions')
    expect(viewSource).toContain('periodOptions')
    expect(viewSource).not.toContain('选择月度工作包')
    expect(viewSource).not.toContain('`${item.company} · ${item.period}`')
    expect(viewSource).toContain('工作包待确认')
    expect(viewSource).toContain('凭证待确认')
    expect(viewSource).toContain('activePackage?.company')
    expect(viewSource).toContain('activePackage?.period')
    expect(viewSource).toContain('workspace.selectPackage(packageId)')
    expect(viewSource).toContain('凭证处理流程')
    expect(viewSource).toContain('AI 预处理')
    expect(viewSource).toContain('AI 推荐处理')
    expect(viewSource).toContain('人工确认')
    expect(viewSource).toContain('原始台账凭证整理')
    expect(viewSource).toContain('从资金流水或发票台账进入凭证核对')
    expect(viewSource).toContain('当月整理摘要')
    expect(viewSource).toContain('完全配对')
    expect(viewSource).toContain('差额补齐')
    expect(viewSource).toContain('单边补齐')
    expect(viewSource).toContain('历史延续')
    expect(viewSource).toContain('api.sourceLedgers.summary')
    expect(viewSource).toContain('请按顺序核对 AI 推荐、异常提示和分录金额')
    expect(viewSource).toContain('第 1 步：原始数据')
    expect(viewSource).toContain('来源汇总')
    expect(viewSource).toContain('sourceSummary')
    expect(viewSource).toContain('银行流水合计')
    expect(viewSource).toContain('发票合计')
    expect(viewSource).toContain('差额金额')
    expect(viewSource).toContain('AI 补齐建议')
    expect(viewSource).toContain('来源明细')
    expect(viewSource).toContain('sourceDetailRows')
    expect(viewSource).toContain('source-line-bank')
    expect(viewSource).toContain('source-line-invoice')
    expect(viewSource).toContain('source-line-difference')
    expect(viewSource).toContain('银行流水')
    expect(viewSource).toContain('发票合计')
    expect(viewSource).toContain('匹配记录')
    expect(viewSource).toContain('sourceBankTransaction')
    expect(viewSource).toContain('sourceBankTransactions')
    expect(viewSource).toContain('sourceInvoice')
    expect(viewSource).toContain('sourceInvoices')
    expect(viewSource).toContain('sourceMatches')
    expect(viewSource).toContain('sourceGroupTypeLabel')
    expect(viewSource).toContain('组合来源')
    expect(viewSource).toContain('missingSourceTreatment')
    expect(viewSource).toContain('缺失发票，建议会计处理')
    expect(viewSource).toContain('缺失流水，建议会计处理')
    expect(viewSource).toContain('调整处理方式')
    expect(viewSource).toContain('treatmentForm')
    expect(viewSource).toContain('applyTreatmentAdjustment')
    expect(viewSource).toContain('ONE_INVOICE_MULTIPLE_BANK_TRANSACTIONS')
    expect(viewSource).toContain('ONE_BANK_TRANSACTION_MULTIPLE_INVOICES')
    expect(viewSource).toContain('v-for="row in sourceDetailRows"')
    expect(viewSource).toContain('sourceInvoiceSellerName')
    expect(viewSource).toContain('invoiceSellerName')
    expect(viewSource).toContain('invoiceBuyerName')
    expect(viewSource).toContain('invoiceRawValue')
    expect(viewSource).toContain("'销方名称'")
    expect(viewSource).toContain('matched-value')
    expect(viewSource).toContain('matching-field')
    expect(viewSource).toContain('sourceMatch')
    expect(viewSource).toContain('function normalizeSourceData(value)')
    expect(viewSource).toContain('JSON.parse(value)')
    expect(viewSource).toContain('voucher.source_data ?? voucher.sourceData')
    expect(viewSource).toContain('function invoiceDirectionLabel(value)')
    expect(viewSource).toContain("OUTPUT: '销项发票'")
    expect(viewSource).toContain('function matchMethodLabel(value)')
    expect(viewSource).toContain('grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr)')
    expect(viewSource).toContain('size="large"')
    expect(viewSource).toContain('position: sticky')
    expect(viewSource).toContain('第 2 步：AI 推荐说明')
    expect(viewSource).toContain('第 3 步：人工确认')
    expect(viewSource).toContain('AI 置信度')
    expect(viewSource).toContain('借方')
    expect(viewSource).toContain('贷方')
    expect(viewSource).toContain('刷新')
    expect(viewSource).toContain('@click="refreshVouchers"')
    expect(viewSource).toContain('async function refreshVouchers()')
    expect(viewSource).toContain('const didRefresh = await loadVouchers(activePackageId.value)')
    expect(viewSource).toContain('凭证列表已刷新')
    expect(viewSource).not.toContain('@click="loadVouchers"')
    expect(viewSource).toContain('确认凭证')
    expect(viewSource).toContain('标记不正确')
    expect(viewSource).toContain('重新匹配')
    expect(viewSource).toContain('撤销确认')
    expect(viewSource).toContain('恢复待确认')
    expect(viewSource).toContain('rematchDialogVisible')
    expect(viewSource).toContain("width=\"min(1280px, 92vw)\"")
    expect(viewSource).toContain('rematchInvoiceSearch')
    expect(viewSource).toContain('rematchBankSearch')
    expect(viewSource).toContain('rematchMode')
    expect(viewSource).toContain('rematchModeOptions')
    expect(viewSource).toContain('保留流水重选发票')
    expect(viewSource).toContain('保留发票重选流水')
    expect(viewSource).toContain('两边都重选')
    expect(viewSource).toContain('filteredRematchInvoiceCandidates')
    expect(viewSource).toContain('filteredRematchBankCandidates')
    expect(viewSource).toContain('placeholder="搜索日期、对方、金额、发票号或理由"')
    expect(viewSource).toContain('rematchCandidatePopover')
    expect(viewSource).toContain('rematchCandidateDirectionLabel')
    expect(viewSource).toContain('rematchCandidateCounterpartyLabel')
    expect(viewSource).toContain('rematchPairPreview')
    expect(viewSource).toContain('新配对预览')
    expect(viewSource).toContain(':class="rematchPanelClass"')
    expect(viewSource).toContain('const rematchPanelClass = computed')
    expect(viewSource).toContain('rematch-panels-single')
    expect(viewSource).toContain('rematch-panels-dual')
    expect(viewSource).toContain('rematch-table-wrap')
    expect(viewSource).toContain('overflow-x: auto')
    expect(viewSource).toContain('发票方向')
    expect(viewSource).toContain('收付方向')
    expect(viewSource).toContain('候选状态')
    expect(viewSource).toContain('rematchCandidateStatusLabel')
    expect(viewSource).toContain('rematchCandidateRowClass')
    expect(viewSource).toContain('isRematchCandidateSelectable')
    expect(viewSource).toContain('selectedRematchInvoiceIds')
    expect(viewSource).toContain('selectedRematchBankIds')
    expect(viewSource).toContain('toggleRematchInvoice')
    expect(viewSource).toContain('toggleRematchBank')
    expect(viewSource).toContain('payload.invoice_ids')
    expect(viewSource).toContain('payload.bank_transaction_ids')
    expect(viewSource).toContain('openRematchDialog')
    expect(viewSource).toContain('applyRematch')
    expect(viewSource).toContain('应用重新匹配')
    expect(viewSource).toContain('async function reopenVoucher()')
    expect(viewSource).toContain('canReopenVoucher')
    expect(viewSource).toContain('async function rejectVoucher()')
    expect(viewSource).toContain('api.vouchers.reject')
    expect(viewSource).toContain('api.vouchers.reopen')
    expect(viewSource).toContain('api.vouchers.rematchCandidates')
    expect(viewSource).toContain('api.vouchers.rematch')
    expect(viewSource).toContain('凭证已标记为不正确')
    expect(viewSource).toContain('凭证已恢复为待确认')
    expect(viewSource).toContain('凭证已重新匹配')
    expect(viewSource).toContain("REJECTED: '已驳回'")
    expect(viewSource).toContain('function packageStatusLabel(value)')
    expect(viewSource).toContain("PENDING_CONFIRMATION: '待确认'")
    expect(viewSource).toContain('function validationErrorLabel(value)')
    expect(viewSource).toContain("DATE_OUT_OF_PERIOD: '凭证日期不在当前会计期间'")
    expect(viewSource).toContain("SOURCE_REASSIGNED: '来源已被其他凭证重新匹配'")
    expect(viewSource).toContain('validationErrorLabels.join')
    expect(viewSource).toContain('function selectNextPendingVoucher(previousVoucherId)')
    expect(viewSource).toContain('selectNextPendingVoucher(voucherId)')
    expect(viewSource).toContain('await workspace.loadWorkspace(packageId)')
    expect(viewSource).toContain('async function preprocessVouchers()')
    expect(viewSource).toContain('api.vouchers.preprocess')
    expect(viewSource).toContain('loadSourceLedgers(packageId, requestId)')
    expect(viewSource).toContain('Promise.allSettled')
    expect(viewSource).toContain('部分原始台账加载失败，已保留当前凭证列表')
    expect(viewSource).toContain('created_vouchers')
    expect(viewSource).toContain('Kimi AI 预处理已完成')
    expect(viewSource).toContain('AI 预处理失败')
    expect(viewSource).not.toContain('api.vouchers.generate')
    expect(viewSource).not.toContain('生成草稿并 AI 推荐')
    expect(viewSource).not.toContain('本次没有生成新的凭证草稿')
    expect(viewSource).toContain('api.vouchers.confirm')
    expect(viewSource).toContain("confirmed_by: 'operator'")
    expect(viewSource).toContain('function isConfirmed(voucher)')
    expect(viewSource).toContain('if (isRejected(voucher)) return false')
    expect(viewSource).toContain('function formatConfidence(value)')
    expect(viewSource).toContain('return `${Math.round(confidence)}%`')
    expect(viewSource).not.toContain('confidence * 100')
    expect(viewSource).toContain('voucherLoadRequestId')
    expect(viewSource).toContain('preprocessRequestId')
    expect(viewSource).toContain('requestId !== voucherLoadRequestId')
    expect(viewSource).toContain('packageId !== activePackageId.value')
    expect(clientSource).toContain('vouchers')
    expect(clientSource).toContain('/monthly-packages/${packageId}/vouchers')
    expect(clientSource).toContain('/monthly-packages/${packageId}/vouchers/generate')
    expect(clientSource).toContain('/vouchers/${voucherId}/confirm')
    expect(clientSource).toContain('/vouchers/${voucherId}/reject')
    expect(clientSource).toContain('/vouchers/${voucherId}/reopen')
    expect(clientSource).toContain('/vouchers/${voucherId}/rematch-candidates')
    expect(clientSource).toContain('/vouchers/${voucherId}/rematch')
    expect(clientSource).toContain('/vouchers/${voucherId}/treatment-adjustment')
    expect(routerSource).toContain('/vouchers')
    expect(routerSource).toContain('../views/VoucherWorkbenchView.vue')
  })

  it('uses source-ledger tabs as the primary voucher workbench list', () => {
    expect(viewSource).toContain('按资金流水整理')
    expect(viewSource).toContain('按发票台账整理')
    expect(viewSource).toContain('<BankLedgerTable')
    expect(viewSource).toContain('<InvoiceLedgerTable')
    expect(viewSource).toContain('@row-select="selectBankLedgerRow"')
    expect(viewSource).toContain('@row-select="selectInvoiceLedgerRow"')
    expect(viewSource).toContain('api.sourceLedgers.bank(packageId)')
    expect(viewSource).toContain('api.sourceLedgers.invoices(packageId)')
    expect(viewSource).toContain('sourceRowMatchesKeyword')
    expect(viewSource).toContain('function firstLinkedVoucherId(row)')
    expect(viewSource).toContain('请先点击 AI 预处理')
    expect(viewSource).not.toContain('待处理凭证列表')
  })

  it('clicks AI preprocessing through the voucher preprocess API', async () => {
    const wrapper = mountWorkbench()
    api.vouchers.preprocess.mockResolvedValue({
      data: {
        created_vouchers: 1,
        vouchers: [voucherFixture('voucher-2', '预处理新增凭证')],
        audit: preprocessAudit(),
      },
    })

    await flushPromises()
    await aiButton(wrapper).trigger('click')
    await flushPromises()

    expect(api.vouchers.preprocess).toHaveBeenCalledWith('package-1')
    expect(api.workspace.snapshot).toHaveBeenCalledWith('package-1')
    expect(wrapper.text()).toContain('Kimi AI 预处理已完成')
  })

  it('keeps the current preprocess loading state when a stale request finishes', async () => {
    const oldPreprocess = deferred()
    const currentPreprocess = deferred()
    api.vouchers.preprocess
      .mockReturnValueOnce(oldPreprocess.promise)
      .mockReturnValueOnce(currentPreprocess.promise)
    const wrapper = mountWorkbench()

    await flushPromises()
    await aiButton(wrapper).trigger('click')
    expect(api.vouchers.preprocess).toHaveBeenCalledTimes(1)
    await aiButton(wrapper).trigger('click')
    expect(api.vouchers.preprocess).toHaveBeenCalledTimes(2)
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.isGenerating).toBe(true)
    oldPreprocess.resolve({ data: { created_vouchers: 0, vouchers: [], audit: preprocessAudit() } })
    await flushPromises()

    expect(api.vouchers.preprocess).toHaveBeenNthCalledWith(1, 'package-1')
    expect(api.vouchers.preprocess).toHaveBeenNthCalledWith(2, 'package-1')
    expect(wrapper.vm.isGenerating).toBe(true)

    currentPreprocess.resolve({ data: { created_vouchers: 0, vouchers: [], audit: preprocessAudit() } })
    await flushPromises()
  })

  it('preserves loaded voucher review state when source ledger loading fails', async () => {
    api.vouchers.list.mockResolvedValue({ data: [voucherFixture()] })
    api.sourceLedgers.bank.mockRejectedValue(new Error('bank ledger timeout'))

    const wrapper = mountWorkbench()
    await flushPromises()

    expect(wrapper.text()).toContain('收到客户货款')
    expect(wrapper.text()).toContain('第 2 步：AI 推荐说明')
  })

  it('renders matched source summary as bank, invoice, and AI difference rows', async () => {
    api.vouchers.list.mockResolvedValue({ data: [multiSourceVoucherFixture()] })

    const wrapper = mountWorkbench()
    await flushPromises()

    expect(wrapper.text()).toContain('来源汇总')
    expect(wrapper.text()).toContain('银行流水合计')
    expect(wrapper.text()).toContain('1 笔 / 200.00')
    expect(wrapper.text()).toContain('发票合计')
    expect(wrapper.text()).toContain('2 张 / 150.00')
    expect(wrapper.text()).toContain('差额金额')
    expect(wrapper.text()).toContain('50.00')
    expect(wrapper.text()).toContain('AI 补齐建议')
    expect(wrapper.findAll('.source-line-bank')).toHaveLength(1)
    expect(wrapper.findAll('.source-line-invoice')).toHaveLength(2)
    expect(wrapper.findAll('.source-line-difference')).toHaveLength(1)
  })

  it('selects a linked voucher from embedded bank and invoice ledger rows', async () => {
    api.vouchers.list.mockResolvedValue({
      data: [
        voucherFixture('voucher-bank', '银行流水凭证'),
        voucherFixture('voucher-invoice', '发票台账凭证'),
      ],
    })
    api.sourceLedgers.bank.mockResolvedValue({
      data: [{ id: 'bank-row', linked_vouchers: [{ id: 'voucher-bank', status: 'PENDING_CONFIRMATION' }] }],
    })
    api.sourceLedgers.invoices.mockResolvedValue({
      data: [{ id: 'invoice-row', linked_vouchers: [{ id: 'voucher-invoice', status: 'PENDING_CONFIRMATION' }] }],
    })
    const wrapper = mountWorkbench()
    await flushPromises()

    await wrapper.findComponent(BankLedgerTable).vm.$emit('row-select', {
      linked_vouchers: [{ id: 'voucher-bank', status: 'PENDING_CONFIRMATION' }],
    })
    await flushPromises()
    expect(wrapper.text()).toContain('银行流水凭证')

    await wrapper.find('.voucher-filter button:last-child').trigger('click')
    await flushPromises()
    await wrapper.findComponent(InvoiceLedgerTable).vm.$emit('row-select', {
      linked_vouchers: [{ id: 'voucher-invoice', status: 'PENDING_CONFIRMATION' }],
    })
    await flushPromises()
    expect(wrapper.text()).toContain('发票台账凭证')
  })
})

function mountWorkbench() {
  const workspace = useWorkspaceStore()
  workspace.workPackages = workPackages()
  workspace.selectedPackageId = 'package-1'
  return mount(VoucherWorkbenchView, {
    global: {
      directives: {
        loading: {},
      },
      stubs: elementStubs(),
    },
  })
}

function elementStubs() {
  return {
    ElAlert: { template: '<section><slot name="title" /><slot /></section>' },
    ElButton: {
      props: ['disabled', 'loading'],
      emits: ['click'],
      template: '<button type="button" :disabled="disabled" :data-loading="String(Boolean(loading))" @click="$emit(`click`)"><slot /></button>',
    },
    ElCheckbox: { template: '<input type="checkbox" />' },
    ElDialog: { template: '<section><slot /><slot name="footer" /></section>' },
    ElEmpty: { props: ['description'], template: '<p>{{ description }}</p>' },
    ElInput: { template: '<input />' },
    ElOption: true,
    ElPopover: { template: '<span><slot name="reference" /><slot /></span>' },
    ElSegmented: {
      props: ['modelValue', 'options'],
      emits: ['update:modelValue'],
      template: '<div><button v-for="option in options" :key="option.value" type="button" @click="$emit(`update:modelValue`, option.value)">{{ option.label }}</button></div>',
    },
    ElSelect: { template: '<select><slot /></select>' },
    ElTable: { props: ['data'], template: '<table><tbody><tr v-for="row in data" :key="row.id"><td>{{ row.summary }}</td></tr></tbody></table>' },
    ElTableColumn: true,
    ElTag: { template: '<span><slot /></span>' },
  }
}

function workPackages() {
  return [
    { id: 'package-1', enterpriseId: 'enterprise-1', company: '昆山黛珂特电子科技有限公司', period: '2026-04', status: 'PENDING_CONFIRMATION', pending: 1 },
    { id: 'package-2', enterpriseId: 'enterprise-1', company: '昆山黛珂特电子科技有限公司', period: '2026-05', status: 'PENDING_CONFIRMATION', pending: 1 },
  ]
}

function voucherFixture(id = 'voucher-1', summary = '收到客户货款') {
  return {
    id,
    voucher_number: '未编号',
    voucher_date: '2026-04-08',
    summary,
    status: 'PENDING_CONFIRMATION',
    ai_confidence: 92,
    ai_reason: 'AI 推荐说明',
    validation_errors: [],
    entries: [
      { direction: 'DEBIT', account_code: '1002', account_name: '银行存款', amount: '1130.00' },
      { direction: 'CREDIT', account_code: '1122', account_name: '应收账款', amount: '1130.00' },
    ],
    source_data: {
      bank_transaction: { id: 'bank-1', transaction_date: '2026-04-08', summary: '收款', credit_amount: '1130.00' },
    },
  }
}

function multiSourceVoucherFixture() {
  return {
    id: 'voucher-multi',
    voucher_number: '未编号',
    voucher_date: '2026-04-20',
    summary: '确认多张销售发票并补齐收款差额',
    status: 'PENDING_CONFIRMATION',
    ai_confidence: 90,
    ai_reason: '流水金额大于发票，AI 建议将差额暂挂预收账款。',
    validation_errors: [],
    entries: [
      { direction: 'DEBIT', account_code: '1002', account_name: '银行存款', amount: '200.00' },
      { direction: 'CREDIT', account_code: '1122', account_name: '应收账款', amount: '150.00' },
      { direction: 'CREDIT', account_code: '2203', account_name: '预收账款', amount: '50.00' },
    ],
    source_data: {
      source_group_type: 'ONE_BANK_TRANSACTION_MULTIPLE_INVOICES',
      bank_transaction: {
        id: 'bank-1',
        transaction_date: '2026-04-20',
        summary: '电子汇入',
        counterparty_name: '上海安费诺永亿通讯电子有限公司',
        credit_amount: '200.00',
        debit_amount: '0.00',
      },
      invoices: [
        {
          id: 'invoice-1',
          invoice_direction: 'OUTPUT',
          invoice_date: '2026-04-20',
          invoice_number: 'INV-001',
          buyer_name: '上海安费诺永亿通讯电子有限公司',
          seller_name: '昆山黛珂特电子科技有限公司',
          total_amount: '80.00',
        },
        {
          id: 'invoice-2',
          invoice_direction: 'OUTPUT',
          invoice_date: '2026-04-20',
          invoice_number: 'INV-002',
          buyer_name: '上海安费诺永亿通讯电子有限公司',
          seller_name: '昆山黛珂特电子科技有限公司',
          total_amount: '70.00',
        },
      ],
      difference_amount: '50.00',
    },
  }
}

function preprocessAudit() {
  return {
    model: 'kimi-k2',
    input_bank_count: 1,
    input_invoice_count: 1,
    duration_ms: 321,
  }
}

function aiButton(wrapper) {
  return wrapper.findAll('button').find((button) => button.text() === 'AI 预处理')
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((promiseResolve, promiseReject) => {
    resolve = promiseResolve
    reject = promiseReject
  })
  return { promise, resolve, reject }
}
