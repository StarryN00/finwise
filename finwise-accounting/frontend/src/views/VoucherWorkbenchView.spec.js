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
import { ElMessage } from 'element-plus'

vi.mock('element-plus', () => ({
  ElMessage: {
    error: vi.fn(),
    info: vi.fn(() => ({ close: vi.fn() })),
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
      createPreprocessJob: vi.fn(),
      latestPreprocessJob: vi.fn(),
      getPreprocessJob: vi.fn(),
      retryPreprocessJob: vi.fn(),
      cancelPreprocessJob: vi.fn(),
      confirm: vi.fn(),
      reject: vi.fn(),
      reopen: vi.fn(),
      rematchCandidates: vi.fn(),
      rematch: vi.fn(),
      adjustTreatment: vi.fn(),
      mergeSuggestions: vi.fn(),
      applyMergeSuggestion: vi.fn(),
    },
    workspace: {
      snapshot: vi.fn(),
    },
  },
}))

const routerMocks = vi.hoisted(() => ({
  route: { query: {} },
  replace: vi.fn(() => Promise.resolve()),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routerMocks.route,
  useRouter: () => ({ replace: routerMocks.replace }),
}))

const __dirname = dirname(fileURLToPath(import.meta.url))
const viewSource = readFileSync(resolve(__dirname, 'VoucherWorkbenchView.vue'), 'utf8')
const clientSource = readFileSync(resolve(__dirname, '../api/client.js'), 'utf8')
const routerSource = readFileSync(resolve(__dirname, '../router/index.js'), 'utf8')

describe('VoucherWorkbenchView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    routerMocks.route.query = {}
    routerMocks.replace.mockClear()
    const localStorageEntries = new Map()
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: vi.fn((key) => localStorageEntries.get(key) ?? null),
        setItem: vi.fn((key, value) => localStorageEntries.set(key, String(value))),
        removeItem: vi.fn((key) => localStorageEntries.delete(key)),
        clear: vi.fn(() => localStorageEntries.clear()),
      },
    })
    api.vouchers.list.mockResolvedValue({ data: [] })
    api.vouchers.latestPreprocessJob.mockResolvedValue({ data: null })
    api.vouchers.getPreprocessJob.mockResolvedValue({ data: null })
    api.vouchers.mergeSuggestions.mockResolvedValue({ data: { suggestions: [] } })
    api.vouchers.applyMergeSuggestion.mockResolvedValue({ data: voucherFixture('voucher-merged', '合并单边付款') })
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
    expect(viewSource).toContain('AI 建议合并')
    expect(viewSource).toContain('AI 建议合并凭证')
    expect(viewSource).toContain('mergeSuggestionDialogVisible')
    expect(viewSource).toContain('openMergeSuggestionDialog')
    expect(viewSource).toContain('applyMergeSuggestion(suggestion)')
    expect(viewSource).toContain('source_voucher_ids: suggestion.source_voucher_ids')
    expect(viewSource).toContain("applied_by: 'operator'")
    expect(viewSource).toContain('当前操作主体')
    expect(viewSource).toContain('选择企业主体')
    expect(viewSource).toContain('选择工作期间')
    expect(viewSource).toContain('selectedEnterpriseId')
    expect(viewSource).toContain('selectedPeriodPackageId')
    expect(viewSource).toContain('VOUCHER_CONTEXT_STORAGE_KEY')
    expect(viewSource).toContain('restorePersistedContext')
    expect(viewSource).toContain('persistSelectedPackageContext')
    expect(viewSource).toContain('route.query.package_id')
    expect(viewSource).toContain('router.replace')
    expect(viewSource).toContain('window.localStorage.setItem')
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
    expect(viewSource).toContain('双向往来')
    expect(viewSource).toContain('双向往来未开票')
    expect(viewSource).toContain('BIDIRECTIONAL_CURRENT_ACCOUNT')
    expect(viewSource).toContain('往来款暂挂')
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
    expect(viewSource).toContain('voucherDetailDialogVisible')
    expect(viewSource).toContain('voucher-detail-dialog')
    expect(viewSource).toContain('voucher-detail-modal')
    expect(viewSource).toContain('detail-header-actions')
    expect(viewSource).toContain('detail-header-meta')
    expect(viewSource).toContain('entry-preview-table')
    expect(viewSource).toContain('source-focus-panel')
    expect(viewSource).toContain('当前核对对象')
    expect(viewSource).toContain('sourceFocusItems')
    expect(viewSource).toContain('sourceFocusDetail')
    expect(viewSource).toContain('grid-template-columns: minmax(0, 1fr)')
    expect(viewSource).toContain('top: 0')
    expect(viewSource).toContain('max-height: 88vh')
    expect(viewSource).not.toContain('<dl class="detail-metrics">')
    expect(viewSource.indexOf('source-focus-panel')).toBeLessThan(viewSource.indexOf('entry-preview-table'))
    expect(viewSource.indexOf('entry-preview-table')).toBeLessThan(viewSource.indexOf('第 1 步：原始数据'))
    expect(viewSource.indexOf('validation-errors')).toBeLessThan(viewSource.indexOf('第 1 步：原始数据'))
    expect(viewSource.indexOf('entry-preview-table')).toBeLessThan(viewSource.indexOf('validation-errors'))
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
    expect(viewSource).toContain('api.vouchers.createPreprocessJob')
    expect(viewSource).toContain('api.vouchers.latestPreprocessJob')
    expect(viewSource).toContain('api.vouchers.getPreprocessJob')
    expect(viewSource).toContain('api.vouchers.mergeSuggestions')
    expect(viewSource).toContain('api.vouchers.applyMergeSuggestion')
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
    expect(viewSource).toContain('preprocessPollTimer')
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
    expect(clientSource).toContain('/monthly-packages/${packageId}/vouchers/merge-suggestions')
    expect(clientSource).toContain('/monthly-packages/${packageId}/vouchers/merge-suggestions/apply')
    expect(routerSource).toContain('/vouchers')
    expect(routerSource).toContain('../views/VoucherWorkbenchView.vue')
  })

  it('uses source-ledger tabs as the primary voucher workbench list', () => {
    expect(viewSource).toContain('按资金流水整理')
    expect(viewSource).toContain('按发票台账整理')
    expect(viewSource).toContain('<BankLedgerTable')
    expect(viewSource).toContain('<InvoiceLedgerTable')
    expect(viewSource).toContain('bankSourceStatusFilter')
    expect(viewSource).toContain('bankVoucherStatusFilter')
    expect(viewSource).toContain('invoiceSourceStatusFilter')
    expect(viewSource).toContain('invoiceVoucherStatusFilter')
    expect(viewSource).toContain('bankSortField')
    expect(viewSource).toContain('bankSortOrder')
    expect(viewSource).toContain('来源处理状态')
    expect(viewSource).toContain('全部来源状态')
    expect(viewSource).toContain('差额补齐')
    expect(viewSource).toContain('单边处理')
    expect(viewSource).toContain('凭证状态')
    expect(viewSource).toContain('按日期排序')
    expect(viewSource).toContain('按交易对方排序')
    expect(viewSource).toContain('升序')
    expect(viewSource).toContain('降序')
    expect(viewSource).toContain('@row-select="selectBankLedgerRow"')
    expect(viewSource).toContain('@row-select="selectInvoiceLedgerRow"')
    expect(viewSource).toContain('api.sourceLedgers.bank(packageId)')
    expect(viewSource).toContain('api.sourceLedgers.invoices(packageId)')
    expect(viewSource).toContain('sourceRowMatchesKeyword')
    expect(viewSource).toContain('sourceRowMatchesFilter')
    expect(viewSource).toContain('sortLedgerRows')
    expect(viewSource).toContain('pagedBankLedgerRows')
    expect(viewSource).toContain('pagedInvoiceLedgerRows')
    expect(viewSource).toContain('ledgerPageSize')
    expect(viewSource).toContain('const ledgerPageSize = ref(20)')
    expect(viewSource).toContain('<el-pagination')
    expect(viewSource).toContain('当前显示')
    expect(viewSource).toContain('筛选结果')
    expect(viewSource).toContain('原始总数')
    expect(viewSource).toContain('function preferredLinkedVoucherId(row)')
    expect(viewSource).toContain('function sourceEntityCount(source, type)')
    expect(viewSource).toContain('function linkedVoucherTaskPriority(taskType)')
    expect(viewSource).toContain('请先点击 AI 预处理')
    expect(viewSource).not.toContain('全部匹配状态')
    expect(viewSource).not.toContain('待处理凭证列表')
  })

  it('filters and sorts bank ledger rows by source status, voucher status, company, and date/order controls', async () => {
    api.sourceLedgers.bank.mockResolvedValue({
      data: [
        bankLedgerFixture({
          id: 'bank-2',
          transaction_date: '2026-04-02',
          counterparty_name: '乙公司',
          source_processing_status: 'SINGLE_SIDED',
          source_processing_status_label: '单边处理',
          voucher_status: 'PENDING_CONFIRMATION',
        }),
        bankLedgerFixture({
          id: 'bank-1',
          transaction_date: '2026-04-01',
          counterparty_name: '甲公司',
          source_processing_status: 'PAIRED',
          source_processing_status_label: '已配对',
          voucher_status: 'CONFIRMED',
        }),
        bankLedgerFixture({
          id: 'bank-3',
          transaction_date: '2026-04-03',
          counterparty_name: '丙公司',
          source_processing_status: 'SINGLE_SIDED',
          source_processing_status_label: '单边处理',
          voucher_status: 'PENDING_CONFIRMATION',
        }),
      ],
    })
    const wrapper = mountWorkbench()
    await flushPromises()

    wrapper.vm.bankSourceStatusFilter = 'SINGLE_SIDED'
    wrapper.vm.bankVoucherStatusFilter = 'PENDING_CONFIRMATION'
    wrapper.vm.bankSortField = 'transaction_date'
    wrapper.vm.bankSortOrder = 'asc'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.filteredBankLedgerRows.map((row) => row.id)).toStrictEqual(['bank-2', 'bank-3'])

    wrapper.vm.bankSortOrder = 'desc'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.filteredBankLedgerRows.map((row) => row.id)).toStrictEqual(['bank-3', 'bank-2'])

    wrapper.vm.bankSortField = 'counterparty_name'
    wrapper.vm.bankSortOrder = 'asc'
    wrapper.vm.bankLedgerKeyword = '乙公司'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.filteredBankLedgerRows.map((row) => row.id)).toStrictEqual(['bank-2'])
  })

  it('paginates source ledgers and shows filtered result counts', async () => {
    api.sourceLedgers.bank.mockResolvedValue({
      data: Array.from({ length: 60 }, (_, index) =>
        bankLedgerFixture({
          id: `bank-${index + 1}`,
          transaction_date: `2026-04-${String((index % 28) + 1).padStart(2, '0')}`,
          counterparty_name: index === 55 ? '目标客户' : `客户${index + 1}`,
        }),
      ),
    })
    const wrapper = mountWorkbench()
    await flushPromises()

    expect(wrapper.vm.pagedBankLedgerRows).toHaveLength(20)
    expect(wrapper.text()).toContain('当前显示 20 条 / 筛选结果 60 条 / 原始总数 60 条')

    wrapper.vm.bankLedgerPage = 2
    wrapper.vm.bankLedgerKeyword = '目标客户'
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.bankLedgerPage).toBe(1)
    expect(wrapper.vm.pagedBankLedgerRows.map((row) => row.id)).toStrictEqual(['bank-56'])
    expect(wrapper.text()).toContain('当前显示 1 条 / 筛选结果 1 条 / 原始总数 60 条')
  })

  it('restores the selected enterprise and period after a browser refresh', async () => {
    window.localStorage.setItem(
      'finwise:voucher-workbench:context',
      JSON.stringify({ package_id: 'package-2', enterprise_id: 'enterprise-1', period: '2026-05' }),
    )

    const wrapper = mountWorkbench()
    await flushPromises()

    const workspace = useWorkspaceStore()
    expect(workspace.selectedPackageId).toBe('package-2')
    expect(wrapper.vm.selectedEnterpriseId).toBe('enterprise-1')
    expect(wrapper.vm.selectedPeriodPackageId).toBe('package-2')
    expect(api.vouchers.list).toHaveBeenCalledWith('package-2')
    expect(routerMocks.replace).toHaveBeenCalledWith({
      query: {
        package_id: 'package-2',
        enterprise_id: 'enterprise-1',
        period: '2026-05',
      },
    })
  })

  it('queues AI preprocessing and keeps task progress after the request returns', async () => {
    const wrapper = mountWorkbench()
    api.vouchers.createPreprocessJob.mockResolvedValue({
      data: {
        id: 'job-1',
        status: 'QUEUED',
        model: 'kimi-k2.6',
        input_bank_count: 81,
        input_invoice_count: 100,
        total_batches: 3,
        completed_batches: 0,
        failed_batches: 0,
        created_vouchers: 0,
        batches: [],
      },
    })
    api.vouchers.getPreprocessJob.mockResolvedValue({
      data: {
        id: 'job-1',
        status: 'RUNNING',
        model: 'kimi-k2.6',
        input_bank_count: 81,
        input_invoice_count: 100,
        total_batches: 3,
        completed_batches: 1,
        failed_batches: 0,
        created_vouchers: 0,
        batches: [],
      },
    })

    await flushPromises()
    await aiButton(wrapper).trigger('click')
    await flushPromises()

    expect(api.vouchers.createPreprocessJob).toHaveBeenCalledWith('package-1')
    expect(api.vouchers.getPreprocessJob).toHaveBeenCalledWith('job-1')
    expect(wrapper.text()).toContain('AI 预处理进行中（1/3 批）')
    wrapper.unmount()
  })

  it('reloads source ledgers after AI preprocessing reaches success', async () => {
    const wrapper = mountWorkbench()
    api.vouchers.createPreprocessJob.mockResolvedValue({ data: queuedPreprocessJob() })
    api.vouchers.getPreprocessJob.mockResolvedValue({
      data: { ...queuedPreprocessJob(), status: 'SUCCEEDED', completed_batches: 3, created_vouchers: 416 },
    })
    api.sourceLedgers.bank.mockClear()
    api.sourceLedgers.invoices.mockClear()

    await flushPromises()
    await aiButton(wrapper).trigger('click')
    await flushPromises()

    expect(api.sourceLedgers.bank).toHaveBeenCalledWith('package-1')
    expect(api.sourceLedgers.invoices).toHaveBeenCalledWith('package-1')
    expect(wrapper.vm.isGenerating).toBe(false)
    wrapper.unmount()
  })

  it('cancels a queued AI preprocessing task through its explicit API action', async () => {
    const wrapper = mountWorkbench()
    api.vouchers.createPreprocessJob.mockResolvedValue({
      data: queuedPreprocessJob(),
    })
    api.vouchers.getPreprocessJob.mockResolvedValue({ data: queuedPreprocessJob() })
    api.vouchers.cancelPreprocessJob.mockResolvedValue({
      data: { ...queuedPreprocessJob(), status: 'CANCELLED', error_summary: '操作员已取消 AI 预处理任务。' },
    })

    await flushPromises()
    await aiButton(wrapper).trigger('click')
    await flushPromises()
    const cancelButton = wrapper.findAll('button').find((button) => button.text().includes('取消任务'))
    await cancelButton.trigger('click')
    await flushPromises()

    expect(api.vouchers.cancelPreprocessJob).toHaveBeenCalledWith('job-1')
    expect(wrapper.text()).toContain('操作员已取消 AI 预处理任务。')
    wrapper.unmount()
  })

  it('requeues failed AI preprocessing batches through the retry action', async () => {
    const wrapper = mountWorkbench()
    api.vouchers.retryPreprocessJob.mockResolvedValue({ data: queuedPreprocessJob() })

    await flushPromises()
    wrapper.vm.preprocessJob = {
      ...queuedPreprocessJob(),
      status: 'PARTIAL_FAILED',
      failed_batches: 1,
      error_summary: '部分批次失败',
    }
    await wrapper.vm.$nextTick()
    const retryButton = wrapper.findAll('button').find((button) => button.text().includes('重试失败批次'))
    await retryButton.trigger('click')
    await flushPromises()

    expect(api.vouchers.retryPreprocessJob).toHaveBeenCalledWith('job-1')
    expect(wrapper.vm.preprocessJob.status).toBe('QUEUED')
    wrapper.unmount()
  })

  it('loads and applies AI merge suggestions with explicit source voucher ids', async () => {
    const suggestion = mergeSuggestionFixture()
    delete suggestion.source_count
    api.vouchers.mergeSuggestions.mockResolvedValue({ data: { suggestions: [suggestion] } })
    api.vouchers.applyMergeSuggestion.mockResolvedValue({
      data: voucherFixture('voucher-merged', '合并同对方单边付款'),
    })
    const wrapper = mountWorkbench()
    await flushPromises()

    await mergeSuggestionButton(wrapper).trigger('click')
    await flushPromises()

    expect(api.vouchers.mergeSuggestions).toHaveBeenCalledWith('package-1')
    expect(wrapper.text()).toContain('昆山合并供应商有限公司')
    expect(wrapper.text()).toContain('2026-04-07')
    expect(wrapper.text()).toContain('付款/转出')
    expect(wrapper.text()).toContain('1123 / 1002')
    expect(wrapper.text()).toContain('应用合并')

    await applyMergeSuggestionButton(wrapper).trigger('click')
    await flushPromises()

    expect(api.vouchers.applyMergeSuggestion).toHaveBeenCalledWith('package-1', {
      source_voucher_ids: ['voucher-a', 'voucher-b', 'voucher-c'],
      applied_by: 'operator',
    })
    expect(api.workspace.snapshot).toHaveBeenCalledWith('package-1')
    expect(api.vouchers.list).toHaveBeenCalledWith('package-1')
    expect(ElMessage.success).toHaveBeenCalledWith('已合并 3 条流水为一张待确认凭证')
    expect(wrapper.vm.selectedVoucherId).toBe('voucher-merged')
    expect(wrapper.vm.voucherDetailDialogVisible).toBe(true)
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
    expect(wrapper.text()).toContain('当前核对对象')
    expect(wrapper.text()).toContain('1 笔流水 + 2 张发票')
    expect(wrapper.text()).toContain('上海安费诺永亿通讯电子有限公司')
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
    expect(wrapper.findAll('.source-focus-item-bank')).toHaveLength(1)
    expect(wrapper.findAll('.source-focus-item-invoice')).toHaveLength(2)
    expect(wrapper.findAll('.source-focus-item-difference')).toHaveLength(1)
  })

  it('labels positive difference amount as invoice amount greater than bank amount', async () => {
    api.vouchers.list.mockResolvedValue({ data: [positiveDifferenceVoucherFixture()] })

    const wrapper = mountWorkbench()
    await flushPromises()

    expect(wrapper.text()).toContain('发票金额大于流水，需补齐应收/应付项目')
    expect(wrapper.text()).not.toContain('流水金额大于发票，需补齐暂收/预付项目')
  })

  it('labels bank fee source focus instead of pretending the summary is a counterparty', async () => {
    api.vouchers.list.mockResolvedValue({ data: [voucherFixture('voucher-bank-only', '记录银行付款待补发票')] })

    const wrapper = mountWorkbench()
    await flushPromises()

    const bankFocus = wrapper.find('.source-focus-item-bank')
    expect(bankFocus.exists()).toBe(true)
    expect(bankFocus.find('strong').text()).toBe('银行收费')
    expect(bankFocus.attributes('title')).toContain('交易对方：银行收费')
    expect(bankFocus.attributes('title')).toContain('流水摘要：收费')
  })

  it('keeps ordinary bank transfers with missing counterparty visibly unresolved', async () => {
    const voucher = voucherFixture('voucher-missing-counterparty', '记录银行付款待补发票')
    voucher.source_data.bank_transaction.summary = '电子转账'
    voucher.source_data.bank_transaction.raw_row_data = { 对方户名: '', 备注: '' }
    api.vouchers.list.mockResolvedValue({ data: [voucher] })

    const wrapper = mountWorkbench()
    await flushPromises()

    const bankFocus = wrapper.find('.source-focus-item-bank')
    expect(bankFocus.find('strong').text()).toBe('对方户名缺失')
    expect(bankFocus.attributes('title')).toContain('交易对方：对方户名缺失')
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
    expect(wrapper.vm.voucherDetailDialogVisible).toBe(true)
    expect(wrapper.text()).toContain('银行流水凭证')

    await wrapper.find('.voucher-filter button:last-child').trigger('click')
    await flushPromises()
    wrapper.vm.voucherDetailDialogVisible = false
    await wrapper.findComponent(InvoiceLedgerTable).vm.$emit('row-select', {
      linked_vouchers: [{ id: 'voucher-invoice', status: 'PENDING_CONFIRMATION' }],
    })
    await flushPromises()
    expect(wrapper.vm.voucherDetailDialogVisible).toBe(true)
    expect(wrapper.text()).toContain('发票台账凭证')
  })

  it('opens the aggregate linked voucher when a ledger row has multiple voucher links', async () => {
    const singleVoucher = {
      ...voucherFixture('voucher-single', '确认销售收入并收款'),
      source_data: {
        bank_transaction: {
          id: 'bank-1',
          transaction_date: '2026-04-20',
          summary: '电子汇入',
          counterparty_name: '上海安费诺永亿通讯电子有限公司',
          credit_amount: '200.00',
          debit_amount: '0.00',
        },
        invoice: {
          id: 'invoice-single',
          invoice_direction: 'OUTPUT',
          invoice_date: '2026-04-20',
          invoice_number: 'INV-SINGLE',
          buyer_name: '上海安费诺永亿通讯电子有限公司',
          seller_name: '昆山黛珂特电子科技有限公司',
          total_amount: '80.00',
        },
      },
    }
    api.vouchers.list.mockResolvedValue({
      data: [singleVoucher, multiSourceVoucherFixture()],
    })
    api.sourceLedgers.bank.mockResolvedValue({
      data: [
        bankLedgerFixture({
          id: 'bank-1',
          linked_invoice_count: 2,
          linked_vouchers: [
            { id: 'voucher-single', status: 'CONFIRMED', task_type: 'UNKNOWN' },
            { id: 'voucher-multi', status: 'PENDING_CONFIRMATION', task_type: 'DIFFERENCE_COMPLETION' },
          ],
        }),
      ],
    })

    const wrapper = mountWorkbench()
    await flushPromises()

    await wrapper.findComponent(BankLedgerTable).vm.$emit('row-select', {
      linked_invoice_count: 2,
      linked_vouchers: [
        { id: 'voucher-single', status: 'CONFIRMED', task_type: 'UNKNOWN' },
        { id: 'voucher-multi', status: 'PENDING_CONFIRMATION', task_type: 'DIFFERENCE_COMPLETION' },
      ],
    })
    await flushPromises()

    expect(wrapper.vm.voucherDetailDialogVisible).toBe(true)
    expect(wrapper.text()).toContain('确认多张销售发票并补齐收款差额')
    expect(wrapper.text()).toContain('1 笔流水 + 2 张发票')
    expect(wrapper.findAll('.source-line-invoice')).toHaveLength(2)
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
    ElDialog: {
      props: ['modelValue', 'title'],
      template: '<section class="dialog-stub" :data-open="String(Boolean(modelValue))"><h2 v-if="title">{{ title }}</h2><slot /><slot name="footer" /></section>',
    },
    ElEmpty: { props: ['description'], template: '<p>{{ description }}</p>' },
    ElInput: { template: '<input />' },
    ElOption: true,
    ElPagination: {
      props: ['currentPage', 'pageSize', 'total'],
      emits: ['update:currentPage', 'update:pageSize'],
      template: '<nav><button type="button" @click="$emit(`update:currentPage`, currentPage + 1)">下一页</button><slot /></nav>',
    },
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
      bank_transaction: {
        id: 'bank-1',
        transaction_date: '2026-04-08',
        summary: '收费',
        debit_amount: '32.00',
        credit_amount: '0.00',
        raw_row_data: {
          对方户名: '',
          备注: '收费项目:对公人民币转账、汇款（含退汇）-对公资金划转跨行同城',
        },
      },
    },
  }
}

function bankLedgerFixture(overrides = {}) {
  return {
    id: 'bank-row',
    transaction_date: '2026-04-08',
    summary: '电子汇入',
    direction_label: '收款/转入',
    counterparty_name: '客户A',
    credit_amount: '1130.00',
    debit_amount: '0',
    balance: '1130.00',
    matching_status: 'MATCHED',
    matching_status_label: '已匹配',
    source_processing_status: 'PAIRED',
    source_processing_status_label: '已配对',
    voucher_status: 'PENDING_CONFIRMATION',
    voucher_status_label: '待确认',
    linked_invoice_count: 1,
    linked_vouchers: [],
    ...overrides,
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

function positiveDifferenceVoucherFixture() {
  const voucher = multiSourceVoucherFixture()
  return {
    ...voucher,
    entries: [
      { direction: 'DEBIT', account_code: '1002', account_name: '银行存款', amount: '150.00' },
      { direction: 'DEBIT', account_code: '1122', account_name: '应收账款', amount: '50.00' },
      { direction: 'CREDIT', account_code: '5001', account_name: '主营业务收入', amount: '176.99' },
      { direction: 'CREDIT', account_code: '22210102', account_name: '销项税额', amount: '23.01' },
    ],
    source_data: {
      ...voucher.source_data,
      bank_transaction: {
        ...voucher.source_data.bank_transaction,
        credit_amount: '150.00',
      },
      invoices: [
        {
          ...voucher.source_data.invoices[0],
          total_amount: '100.00',
        },
        {
          ...voucher.source_data.invoices[1],
          total_amount: '100.00',
        },
      ],
      difference_amount: '50.00',
    },
  }
}

function mergeSuggestionFixture() {
  return {
    suggestion_id: 'merge-suggestion-test',
    counterparty_name: '昆山合并供应商有限公司',
    direction: 'OUTFLOW',
    direction_label: '付款合并',
    source_count: 3,
    total_amount: '600.00',
    confidence: 88,
    recommended_summary: '合并记录同对方付款待补发票',
    recommended_debit_account_code: '1123',
    recommended_debit_account_name: '预付账款',
    recommended_credit_account_code: '1002',
    recommended_credit_account_name: '银行存款',
    source_voucher_ids: ['voucher-a', 'voucher-b', 'voucher-c'],
    reason: '同对方、同付款方向、同会计处理，适合合并为一张凭证。',
    sources: [
      {
        voucher_id: 'voucher-a',
        transaction_date: '2026-04-07',
        counterparty_name: '昆山合并供应商有限公司',
        direction: 'OUTFLOW',
        direction_label: '付款/转出',
        debit_account_code: '1123',
        credit_account_code: '1002',
        voucher_number: '未编号',
        summary: '电子转账',
        amount: '100.00',
      },
      {
        voucher_id: 'voucher-b',
        transaction_date: '2026-04-08',
        counterparty_name: '昆山合并供应商有限公司',
        direction: 'OUTFLOW',
        direction_label: '付款/转出',
        debit_account_code: '1123',
        credit_account_code: '1002',
        voucher_number: '未编号',
        summary: '电子转账',
        amount: '200.00',
      },
      {
        voucher_id: 'voucher-c',
        transaction_date: '2026-04-09',
        counterparty_name: '昆山合并供应商有限公司',
        direction: 'OUTFLOW',
        direction_label: '付款/转出',
        debit_account_code: '1123',
        credit_account_code: '1002',
        voucher_number: '未编号',
        summary: '电子转账',
        amount: '300.00',
      },
    ],
  }
}

function queuedPreprocessJob() {
  return {
    id: 'job-1',
    status: 'QUEUED',
    model: 'kimi-k2.6',
    input_bank_count: 81,
    input_invoice_count: 100,
    total_batches: 3,
    completed_batches: 0,
    failed_batches: 0,
    created_vouchers: 0,
    batches: [],
  }
}

function aiButton(wrapper) {
  return wrapper.findAll('button').find((button) => button.text().includes('AI 预处理'))
}

function mergeSuggestionButton(wrapper) {
  return wrapper.findAll('button').find((button) => button.text().includes('AI 建议合并'))
}

function applyMergeSuggestionButton(wrapper) {
  return wrapper.findAll('button').find((button) => button.text().includes('应用合并'))
}
