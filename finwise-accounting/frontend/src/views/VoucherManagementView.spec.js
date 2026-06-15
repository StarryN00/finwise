// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import VoucherManagementView from './VoucherManagementView.vue'
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
    vouchers: {
      list: vi.fn(),
    },
    historicalImports: {
      vouchers: vi.fn(),
    },
    workspace: {
      snapshot: vi.fn(),
    },
  },
}))

const confirmedVoucher = {
  id: 'voucher-1',
  voucher_date: '2026-04-24',
  voucher_number: '记-0065',
  summary: '销聚之利',
  attachment_count: 1,
  status: 'CONFIRMED',
  confirmed_at: '2026-05-30T10:30:00',
  source_key: 'match:1',
  source_data: {
    source_group_type: 'BANK_AND_INVOICE',
    bank_transaction: {
      transaction_date: '2026-04-24',
      counterparty_name: '昆山聚之利电子有限公司',
      credit_amount: '163328.00',
    },
    invoice: {
      invoice_direction: 'OUTPUT',
      buyer_name: '昆山聚之利电子有限公司',
      total_amount: '163328.00',
    },
  },
  entries: [
    {
      line_no: 1,
      direction: 'DEBIT',
      account_code: '1122031',
      account_name: '应收账款_昆山聚之利电子有限公司',
      amount: '163328.00',
    },
    {
      line_no: 2,
      direction: 'CREDIT',
      account_code: '5001',
      account_name: '主营业务收入',
      amount: '144538.05',
    },
    {
      line_no: 3,
      direction: 'CREDIT',
      account_code: '22210107',
      account_name: '应交税费_应交增值税_销项税额',
      amount: '18789.95',
    },
  ],
}

function confirmedVoucherAt(index) {
  const padded = String(index).padStart(4, '0')
  return {
    ...confirmedVoucher,
    id: `voucher-${padded}`,
    voucher_number: `记-${padded}`,
    voucher_date: `2026-04-${String(Math.min(index, 28)).padStart(2, '0')}`,
    summary: `已确认凭证 ${padded}`,
  }
}

function mountView() {
  return mount(VoucherManagementView, {
    global: {
      stubs: {
        ElButton: buttonStub(),
        ElInput: inputStub(),
        ElSelect: selectStub(),
        ElOption: optionStub(),
        ElTable: tableStub(),
        ElTableColumn: true,
        ElTag: { template: '<span class="el-tag"><slot /></span>' },
        ElDialog: dialogStub(),
      },
    },
  })
}

function buttonStub() {
  return {
    props: ['loading', 'type'],
    emits: ['click'],
    template: '<button type="button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
  }
}

function inputStub() {
  return {
    props: ['modelValue', 'placeholder'],
    emits: ['update:modelValue', 'keyup'],
    template:
      '<input :placeholder="placeholder" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" @keyup="$emit(\'keyup\', $event)" />',
  }
}

function selectStub() {
  return {
    props: ['modelValue', 'placeholder'],
    emits: ['update:modelValue'],
    template: '<select :aria-label="placeholder" :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
  }
}

function optionStub() {
  return {
    props: ['label', 'value'],
    template: '<option :value="value">{{ label }}</option>',
  }
}

function tableStub() {
  return {
    props: ['data'],
    template: '<div class="stub-table"><slot />{{ JSON.stringify(data) }}</div>',
  }
}

function dialogStub() {
  return {
    props: ['modelValue', 'title'],
    template: '<section v-if="modelValue" class="stub-dialog"><h2>{{ title }}</h2><slot /></section>',
  }
}

describe('VoucherManagementView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: vi.fn(() => null),
        setItem: vi.fn(),
      },
    })
    api.vouchers.list.mockResolvedValue({ data: [confirmedVoucher] })
    api.historicalImports.vouchers.mockResolvedValue({ data: [] })
    api.workspace.snapshot.mockResolvedValue({
      data: {
        selectedPackageId: 'package-1',
        enterprises: [{ id: 'enterprise-1', name: '昆山黛珂特电子科技有限公司' }],
        workPackages: [
          {
            id: 'package-1',
            enterpriseId: 'enterprise-1',
            company: '昆山黛珂特电子科技有限公司',
            period: '2026-04',
          },
        ],
      },
    })
  })

  it('loads confirmed vouchers with enterprise, period, and keyword filters', async () => {
    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    expect(wrapper.text()).not.toContain('月度工作包')
    expect(wrapper.text()).not.toContain('历史账套')
    expect(wrapper.text()).toContain('企业主体')
    expect(wrapper.text()).toContain('工作期间')
    expect(wrapper.find('select[aria-label="凭证来源"]').exists()).toBe(true)
    expect(api.vouchers.list).toHaveBeenCalledWith('package-1', { status: 'CONFIRMED' })
    expect(api.historicalImports.vouchers).toHaveBeenCalledWith('enterprise-1', {
      fiscal_year: 2026,
      period_start_month: 4,
      period_end_month: 4,
    })

    await wrapper.find('input[placeholder="可输入凭证号/摘要/科目/金额..."]').setValue('聚之利')
    await wrapper.find('button.icon-search-button').trigger('click')
    await flushPromises()

    expect(api.vouchers.list).toHaveBeenLastCalledWith('package-1', { status: 'CONFIRMED', keyword: '聚之利' })
    expect(api.historicalImports.vouchers).toHaveBeenLastCalledWith('enterprise-1', {
      fiscal_year: 2026,
      period_start_month: 4,
      period_end_month: 4,
      keyword: '聚之利',
    })
    expect(wrapper.find('[data-testid="voucher-count-summary"]').text()).toContain('凭证')
    expect(wrapper.find('[data-testid="voucher-count"]').text()).toBe('1')
  })

  it('renders voucher entries inline with debit, credit, and total rows', async () => {
    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    expect(wrapper.find('.voucher-ledger-table').exists()).toBe(true)
    expect(wrapper.text()).toContain('日期：2026-04-24')
    expect(wrapper.text()).toContain('凭证字号：记-0065')
    expect(wrapper.text()).toContain('附单据 1 张')
    expect(wrapper.text()).toContain('应收账款_昆山聚之利电子有限公司')
    expect(wrapper.text()).toContain('借方金额')
    expect(wrapper.text()).toContain('贷方金额')
    expect(wrapper.text()).toContain('总合计')
    expect(wrapper.text()).toContain('163,328.00')
  })

  it('selects an inline voucher group by clicking the voucher date', async () => {
    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    await wrapper.find('button.voucher-number-link').trigger('click')
    await flushPromises()

    expect(wrapper.find('.voucher-meta-row.selected').exists()).toBe(true)
    expect(wrapper.text()).toContain('凭证字号：记-0065')
  })

  it('only shows implemented toolbar actions and removes fake bulk-selection controls', async () => {
    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    const toolbar = wrapper.find('.voucher-toolbar')
    expect(toolbar.exists()).toBe(true)
    expect(toolbar.text()).toContain('刷新')
    expect(toolbar.find('input[placeholder="可输入凭证号/摘要/科目/金额..."]').exists()).toBe(true)
    expect(toolbar.text()).not.toContain('更多条件')
    expect(toolbar.text()).not.toContain('新增凭证')
    expect(toolbar.text()).not.toContain('批量操作')
    expect(toolbar.text()).not.toContain('导入/导出')
    expect(toolbar.text()).not.toContain('打印')
    expect(toolbar.text()).not.toContain('电子账本')
    expect(toolbar.text()).not.toContain('按日期编号')
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(0)
  })

  it('filters to historical vouchers with dropdown fiscal year and numeric API params', async () => {
    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    const sourceSelect = wrapper.find('select[aria-label="凭证来源"]')
    expect(sourceSelect.exists()).toBe(true)
    await sourceSelect.setValue('historical')
    await flushPromises()

    const yearSelect = wrapper.find('select[aria-label="会计年度"]')
    expect(yearSelect.exists()).toBe(true)
    expect(wrapper.find('input[placeholder="会计年度"]').exists()).toBe(false)

    await yearSelect.setValue('2025')
    await flushPromises()

    expect(api.historicalImports.vouchers).toHaveBeenLastCalledWith('enterprise-1', {
      fiscal_year: 2025,
      period_start_month: 4,
      period_end_month: 4,
    })
  })

  it('shows a focused empty state instead of an empty ledger table when no confirmed vouchers exist', async () => {
    api.vouchers.list.mockResolvedValue({ data: [] })

    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    expect(wrapper.find('[data-testid="voucher-empty-state"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('当前期间暂无可展示凭证')
    expect(wrapper.text()).toContain('请确认该企业和期间已经完成凭证确认')
    expect(wrapper.text()).toContain('昆山黛珂特电子科技有限公司 · 2026-04')
    expect(wrapper.find('.voucher-ledger-table').exists()).toBe(false)
    expect(wrapper.find('.period-rail').exists()).toBe(false)
    expect(wrapper.find('.pagination-bar').exists()).toBe(false)
  })

  it('lets operators clear keyword from the empty search result state', async () => {
    api.vouchers.list.mockResolvedValue({ data: [] })

    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    await wrapper.find('input[placeholder="可输入凭证号/摘要/科目/金额..."]').setValue('不存在')
    await wrapper.find('button.icon-search-button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('没有找到匹配的凭证')
    const clearButton = wrapper.findAll('button').find((button) => button.text() === '清空搜索')
    expect(clearButton).toBeTruthy()

    await clearButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('input[placeholder="可输入凭证号/摘要/科目/金额..."]').element.value).toBe('')
    expect(api.vouchers.list).toHaveBeenLastCalledWith('package-1', { status: 'CONFIRMED' })
    expect(api.historicalImports.vouchers).toHaveBeenLastCalledWith('enterprise-1', {
      fiscal_year: 2026,
      period_start_month: 4,
      period_end_month: 4,
    })
  })

  it('paginates confirmed vouchers with 20 rows per page by default', async () => {
    api.vouchers.list.mockResolvedValue({
      data: Array.from({ length: 21 }, (_, index) => confirmedVoucherAt(index + 1)),
    })

    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    expect(wrapper.find('[data-testid="voucher-count"]').text()).toBe('21')
    expect(wrapper.text()).toContain('已确认凭证 0020')
    expect(wrapper.text()).not.toContain('已确认凭证 0021')
    expect(wrapper.text()).toContain('每页 20 张凭证')

    await wrapper.find('button.next-page-button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('第 2 / 2 页')
    expect(wrapper.text()).toContain('已确认凭证 0021')
    expect(wrapper.text()).not.toContain('已确认凭证 0001')
  })

  it('uses invoice counterparty name when seller and buyer names are missing', async () => {
    api.vouchers.list.mockResolvedValue({
      data: [
        {
          ...confirmedVoucher,
          id: 'voucher-invoice-counterparty',
          source_data: {
            invoice: {
              invoice_direction: 'INPUT',
              counterparty_name: '苏州顺丰速运有限公司',
              total_amount: '16883.48',
            },
          },
        },
      ],
    })

    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    expect(wrapper.text()).toContain('苏州顺丰速运有限公司')
    expect(wrapper.text()).not.toContain(' - ')
  })

  it('hides non-confirmed vouchers if the API returns mixed statuses', async () => {
    api.vouchers.list.mockResolvedValue({
      data: [
        confirmedVoucher,
        {
          ...confirmedVoucher,
          id: 'voucher-pending',
          status: 'PENDING_CONFIRMATION',
          summary: '待确认凭证不应出现在凭证管理',
        },
        {
          ...confirmedVoucher,
          id: 'voucher-rejected',
          status: 'REJECTED',
          summary: '已驳回凭证不应出现在凭证管理',
        },
      ],
    })

    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    expect(wrapper.find('[data-testid="voucher-count"]').text()).toBe('1')
    expect(wrapper.text()).toContain('销聚之利')
    expect(wrapper.text()).not.toContain('待确认凭证不应出现在凭证管理')
    expect(wrapper.text()).not.toContain('已驳回凭证不应出现在凭证管理')
  })

  it('switches periods from the period rail without a source-mode tab', async () => {
    api.workspace.snapshot.mockResolvedValue({
      data: {
        selectedPackageId: 'package-1',
        enterprises: [{ id: 'enterprise-1', name: '昆山黛珂特电子科技有限公司' }],
        workPackages: [
          {
            id: 'package-1',
            enterpriseId: 'enterprise-1',
            company: '昆山黛珂特电子科技有限公司',
            period: '2026-04',
          },
          {
            id: 'package-2',
            enterpriseId: 'enterprise-1',
            company: '昆山黛珂特电子科技有限公司',
            period: '2026-05',
          },
        ],
      },
    })

    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    const mayButton = wrapper.findAll('.period-rail button').find((button) => button.text() === '05月')
    expect(mayButton?.exists()).toBe(true)

    await mayButton.trigger('click')
    await flushPromises()

    expect(api.vouchers.list).toHaveBeenLastCalledWith('package-2', { status: 'CONFIRMED' })
    expect(api.historicalImports.vouchers).toHaveBeenLastCalledWith('enterprise-1', {
      fiscal_year: 2026,
      period_start_month: 5,
      period_end_month: 5,
    })
    expect(wrapper.find('.period-rail button.active').text()).toBe('05月')
  })
})
