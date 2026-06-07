// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import LedgerView from './LedgerView.vue'
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
    ledgers: {
      summary: vi.fn(),
      accounts: vi.fn(),
      journal: vi.fn(),
      general: vi.fn(),
      detail: vi.fn(),
      trialBalance: vi.fn(),
    },
    historicalImports: {
      accounts: vi.fn(),
      journal: vi.fn(),
      general: vi.fn(),
      detail: vi.fn(),
      trialBalance: vi.fn(),
    },
    workspace: {
      snapshot: vi.fn(),
    },
  },
}))

const ledgerRows = Array.from({ length: 21 }, (_, index) => ({
  voucher_id: `voucher-${index + 1}`,
  voucher_entry_id: `entry-${index + 1}`,
  voucher_date: `2026-04-${String(Math.min(index + 1, 28)).padStart(2, '0')}`,
  voucher_number: `记-${String(index + 1).padStart(4, '0')}`,
  summary: `账簿摘要 ${index + 1}`,
  account_code: index % 2 ? '5001' : '1002',
  account_name: index % 2 ? '主营业务收入' : '银行存款',
  direction: index % 2 ? 'CREDIT' : 'DEBIT',
  direction_label: index % 2 ? '贷方' : '借方',
  debit_amount: index % 2 ? '0.00' : '100.00',
  credit_amount: index % 2 ? '100.00' : '0.00',
  source_type: 'TEST',
}))

function mountView() {
  return mount(LedgerView, {
    global: {
      stubs: {
        ElButton: buttonStub(),
        ElInput: inputStub(),
        ElSelect: selectStub(),
        ElOption: optionStub(),
        ElTabs: tabsStub(),
        ElTabPane: tabPaneStub(),
        ElTag: { props: ['type'], template: '<span class="el-tag"><slot /></span>' },
        ElAlert: { props: ['title'], template: '<div class="el-alert">{{ title }}<slot /></div>' },
        ElPagination: paginationStub(),
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
    emits: ['update:modelValue'],
    template: '<input :placeholder="placeholder" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
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

function tabsStub() {
  return {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<div class="tabs"><slot /></div>',
  }
}

function tabPaneStub() {
  return {
    props: ['label', 'name'],
    template: '<section class="tab-pane"><h3>{{ label }}</h3><slot /></section>',
  }
}

function paginationStub() {
  return {
    props: ['currentPage', 'pageSize', 'total'],
    emits: ['update:currentPage'],
    template:
      '<button class="stub-next-page" type="button" @click="$emit(\'update:currentPage\', 2)">next</button>',
  }
}

describe('LedgerView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.ledgers.summary.mockResolvedValue({
      data: {
        confirmed_voucher_count: 2,
        pending_voucher_count: 1,
        entry_count: 4,
        is_final: false,
      },
    })
    api.ledgers.accounts.mockResolvedValue({
      data: [
        { account_code: '1002', account_name: '银行存款', account_category: '资产' },
        { account_code: '5001', account_name: '主营业务收入', account_category: '损益' },
      ],
    })
    api.ledgers.journal.mockResolvedValue({ data: ledgerRows })
    api.ledgers.general.mockResolvedValue({
      data: [
        {
          account_code: '1002',
          account_name: '银行存款',
          account_category: '资产',
          balance_direction_label: '借方',
          opening_debit: '0.00',
          opening_credit: '0.00',
          period_debit: '200.00',
          period_credit: '50.00',
          closing_debit: '150.00',
          closing_credit: '0.00',
        },
      ],
    })
    api.ledgers.detail.mockResolvedValue({
      data: [
        {
          voucher_id: 'voucher-1',
          voucher_entry_id: 'entry-1',
          voucher_date: '2026-04-01',
          voucher_number: '记-0001',
          summary: '收到货款',
          counter_accounts: '主营业务收入',
          counter_account_display: '预收账款 / 上海客户有限公司',
          counter_account_name: '预收账款',
          counter_auxiliary_type: 'COUNTERPARTY',
          counter_auxiliary_name: '上海客户有限公司',
          debit_amount: '200.00',
          credit_amount: '0.00',
          balance_direction_label: '借方',
          balance: '200.00',
        },
      ],
    })
    api.ledgers.trialBalance.mockResolvedValue({
      data: {
        rows: [],
        opening_debit_total: '0.00',
        opening_credit_total: '0.00',
        period_debit_total: '200.00',
        period_credit_total: '200.00',
        closing_debit_total: '200.00',
        closing_credit_total: '200.00',
        is_balanced: true,
        difference: '0.00',
      },
    })
    api.historicalImports.accounts.mockResolvedValue({ data: [] })
    api.historicalImports.journal.mockResolvedValue({ data: [] })
    api.historicalImports.general.mockResolvedValue({ data: [] })
    api.historicalImports.detail.mockResolvedValue({ data: [] })
    api.historicalImports.trialBalance.mockResolvedValue({
      data: {
        rows: [],
        is_balanced: true,
        difference: '0.00',
        opening_debit_total: '0.00',
        opening_credit_total: '0.00',
        period_debit_total: '0.00',
        period_credit_total: '0.00',
        closing_debit_total: '0.00',
        closing_credit_total: '0.00',
      },
    })
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

  it('loads ledger summary and journal rows for the selected package', async () => {
    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    expect(api.ledgers.summary).toHaveBeenCalledWith('package-1')
    expect(api.ledgers.journal).toHaveBeenCalledWith('package-1')
    expect(wrapper.text()).toContain('账簿')
    expect(wrapper.text()).toContain('月度工作包')
    expect(wrapper.text()).toContain('历史账套')
    expect(wrapper.text()).toContain('序时账')
    expect(wrapper.text()).toContain('总账')
    expect(wrapper.text()).toContain('明细账')
    expect(wrapper.text()).toContain('余额表')
    expect(wrapper.text()).toContain('仍有 1 张凭证未确认')
    expect(wrapper.text()).toContain('当前显示 20 条 / 筛选结果 21 条 / 原始总数 21 条')
    expect(wrapper.text()).toContain('账簿摘要 20')
    expect(wrapper.text()).not.toContain('账簿摘要 21')
  })

  it('resets to page one when keyword filtering changes', async () => {
    const wrapper = mountView()
    const workspace = useWorkspaceStore()
    await workspace.loadWorkspace()
    await flushPromises()

    await wrapper.find('.stub-next-page').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('第 2 / 2 页')

    await wrapper.find('input[placeholder="搜索日期、凭证号、摘要、科目"]').setValue('账簿摘要 1')
    await flushPromises()

    expect(wrapper.text()).toContain('第 1 / 1 页')
    expect(wrapper.text()).toContain('筛选结果 11 条')
  })

  it('contains dense-table scroll containers and Chinese ledger labels', () => {
    const source = readFileSync(resolve(__dirname, 'LedgerView.vue'), 'utf8')
    expect(source).toContain('ledger-table-scroll')
    expect(source).toContain('凭证日期')
    expect(source).toContain('会计科目')
    expect(source).toContain('科目编码')
    expect(source).toContain('科目名称')
    expect(source).toContain('对方科目 / 辅助对象')
    expect(source).toContain('counter_account_display')
    expect(source).toContain('借方金额')
    expect(source).toContain('贷方金额')
    expect(source).toContain('期初借方')
    expect(source).toContain('本期贷方')
    expect(source).toContain('期末方向')
    expect(source).toContain('rowClass(row)')
    expect(source).toContain('auxiliary-row')
    expect(source).toContain('account-parent-row')
    expect(source).toContain('const pageSize = 20')
    expect(source).toContain('api.historicalImports.journal')
    expect(source).toContain('api.historicalImports.trialBalance')
  })
})
