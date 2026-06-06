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
        ElOption: true,
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

    expect(wrapper.text()).toContain('凭证管理')
    expect(wrapper.text()).toContain('企业主体')
    expect(wrapper.text()).toContain('工作期间')
    expect(api.vouchers.list).toHaveBeenCalledWith('package-1', { status: 'CONFIRMED' })

    await wrapper.find('input[placeholder="搜索凭证号、摘要、对方主体、科目"]').setValue('聚之利')
    await wrapper.find('button.search-button').trigger('click')
    await flushPromises()

    expect(api.vouchers.list).toHaveBeenLastCalledWith('package-1', { status: 'CONFIRMED', keyword: '聚之利' })
    expect(wrapper.text()).toContain('显示 1 张已确认凭证')
  })

  it('opens an accounting voucher detail dialog from a confirmed voucher row', async () => {
    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    await wrapper.find('button.view-voucher-button').trigger('click')
    await flushPromises()

    expect(wrapper.find('.accounting-voucher-dialog').exists()).toBe(true)
    expect(wrapper.text()).toContain('记账凭证')
    expect(wrapper.text()).toContain('记 字第 0065 号')
    expect(wrapper.text()).toContain('日期：2026-04-24')
    expect(wrapper.text()).toContain('附件 1 张')
    expect(wrapper.text()).toContain('应收账款_昆山聚之利电子有限公司')
    expect(wrapper.text()).toContain('借方金额')
    expect(wrapper.text()).toContain('贷方金额')
    expect(wrapper.text()).toContain('合计')
    expect(wrapper.text()).toContain('壹拾陆万叁仟叁佰贰拾捌元整')
  })

  it('opens the accounting voucher detail dialog by clicking the voucher number', async () => {
    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    await wrapper.find('button.voucher-number-link').trigger('click')
    await flushPromises()

    expect(wrapper.find('.accounting-voucher-dialog').exists()).toBe(true)
    expect(wrapper.text()).toContain('记账凭证')
    expect(wrapper.text()).toContain('记 字第 0065 号')
  })

  it('paginates confirmed vouchers with 20 rows per page by default', async () => {
    api.vouchers.list.mockResolvedValue({
      data: Array.from({ length: 21 }, (_, index) => confirmedVoucherAt(index + 1)),
    })

    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    expect(wrapper.text()).toContain('显示 21 张已确认凭证')
    expect(wrapper.text()).toContain('已确认凭证 0020')
    expect(wrapper.text()).not.toContain('已确认凭证 0021')
    expect(wrapper.text()).toContain('每页 20 条')

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

    expect(wrapper.text()).toContain('显示 1 张已确认凭证')
    expect(wrapper.text()).toContain('销聚之利')
    expect(wrapper.text()).not.toContain('待确认凭证不应出现在凭证管理')
    expect(wrapper.text()).not.toContain('已驳回凭证不应出现在凭证管理')
  })
})
