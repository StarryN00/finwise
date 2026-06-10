// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import HistoricalImportView from './HistoricalImportView.vue'
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
    historicalImports: {
      importGbt24589: vi.fn(),
      list: vi.fn(),
    },
  },
}))

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'HistoricalImportView.vue'), 'utf8')
const clientSource = readFileSync(resolve(__dirname, '../api/client.js'), 'utf8')
const routerSource = readFileSync(resolve(__dirname, '../router/index.js'), 'utf8')

describe('HistoricalImportView', () => {
  it('renders a GB/T24589 historical accounting import workflow in Chinese', () => {
    expect(source).toContain('历史账套导入')
    expect(source).toContain('GB/T24589-2010')
    expect(source).toContain('企业')
    expect(source).toContain('会计年度')
    expect(source).toContain('起始月份')
    expect(source).toContain('截止月份')
    expect(source).toContain('序时账')
    expect(source).toContain('余额表')
    expect(source).toContain('导入历史账套')
    expect(source).toContain('导入批次')
    expect(source).toContain('导入记录')
    expect(source).toContain('导入时间')
    expect(source).toContain('数据时间范围')
    expect(source).toContain('源文件')
    expect(source).toContain('凭证数量')
    expect(source).toContain('借贷不平凭证')
  })

  it('keeps validation summary in a visible horizontal scroll container', () => {
    expect(source).toContain('historical-summary-scroll')
    expect(source).toContain('historical-summary-table')
    expect(source).toContain('overflow-x: auto')
    expect(source).toContain('width: 100%')
    expect(source).toContain('min-width: 980px')
    expect(source).toContain('show-overflow-tooltip')
  })

  it('uses explicit upload handlers instead of passing DOM events into API paths', () => {
    expect(source).toContain('@change="selectLedgerFile"')
    expect(source).toContain('@change="selectBalanceFile"')
    expect(source).toContain('@click="submitHistoricalImport"')
    expect(source).toContain('api.historicalImports.importGbt24589')
    expect(source).toContain('api.historicalImports.list')
    expect(source).toContain('formData.append')
    expect(source).not.toContain('@click="api.')
  })

  it('registers API client and route for the historical import page', () => {
    expect(clientSource).toContain('historicalImports')
    expect(clientSource).toContain('/historical-imports/gbt24589')
    expect(routerSource).toContain('/historical-import')
    expect(routerSource).toContain('HistoricalImportView.vue')
  })

  it('uploads selected ledger and balance files, then shows visible success feedback', async () => {
    setActivePinia(createPinia())
    const workspace = useWorkspaceStore()
    workspace.enterprises = [{ id: 'enterprise-1', name: '昆山黛珂特电子科技有限公司' }]
    api.historicalImports.importGbt24589.mockResolvedValue({
      data: {
        status: 'IMPORTED',
        created_ledger_rows: 4664,
        created_balance_rows: 297,
        validation_summary: {
          voucher_count: 1060,
          ledger_debit_total: '229391224.56',
          ledger_credit_total: '229391224.56',
          balance_period_debit_total: '388311152.83',
          balance_period_credit_total: '388257302.94',
          unbalanced_voucher_count: 0,
          unbalanced_voucher_samples: [],
        },
      },
    })
    api.historicalImports.list.mockResolvedValue({
      data: [
        {
          id: 'batch-1',
          status: 'IMPORTED',
          fiscal_year: 2026,
          period_start_month: 1,
          period_end_month: 3,
          created_ledger_rows: 4664,
          created_balance_rows: 297,
          ledger_filename: '序时账_2026.xls',
          balance_filename: '余额表_2026.xls',
          source_metadata: {
            ledger_period_text: '2026年01月至2026年03月',
            balance_period_text: '2026年01月至2026年03月',
          },
          created_at: '2026-06-10T10:00:00',
        },
      ],
    })
    const wrapper = mount(HistoricalImportView, {
      global: {
        directives: {
          loading: {},
        },
        stubs: {
          DataTableShell: { template: '<section><slot /></section>' },
          PackageContextBar: { template: '<div />' },
          ElButton: { template: '<button type="button" @click="$emit(`click`)"><slot /></button>' },
          ElForm: { template: '<form><slot /></form>' },
          ElFormItem: { template: '<label><slot /></label>' },
          ElInputNumber: { template: '<input />' },
          ElOption: true,
          ElSelect: { template: '<select><slot /></select>' },
          ElTable: {
            props: ['data'],
            template: '<table><tbody><tr v-for="(row, index) in data" :key="row.id || row.label || index"><td v-for="value in row" :key="String(value)">{{ value }}</td></tr></tbody></table>',
          },
          ElTableColumn: true,
          ElTag: { template: '<span><slot /></span>' },
        },
      },
    })
    wrapper.vm.form.fiscalYear = 2026
    wrapper.vm.form.periodStartMonth = 1
    wrapper.vm.form.periodEndMonth = 3

    await selectFile(wrapper, 'input[accept=".xls,.xlsx"]', new File(['ledger'], '序时账_2025.xls'))
    await selectFile(wrapper, 'input[accept=".xls,.xlsx"]', new File(['balance'], '余额表_2025.xls'), 1)
    await wrapper.findAll('button').find((button) => button.text() === '导入历史账套').trigger('click')
    await flushPromises()

    expect(api.historicalImports.importGbt24589).toHaveBeenCalledWith('enterprise-1', expect.any(FormData))
    expect(api.historicalImports.list).toHaveBeenCalledWith('enterprise-1')
    const formData = api.historicalImports.importGbt24589.mock.calls[0][1]
    expect(formData.get('fiscal_year')).toBe('2026')
    expect(formData.get('period_start_month')).toBe('1')
    expect(formData.get('period_end_month')).toBe('3')
    expect(wrapper.text()).toContain('2026 年 1 月至 3 月 历史账套已导入：序时账 4664 行，余额表 297 行')
    expect(wrapper.text()).toContain('2026年01月至2026年03月')
    expect(wrapper.text()).toContain('序时账 4664 行')
    expect(wrapper.text()).toContain('余额表 297 行')
    expect(wrapper.text()).toContain('序时账_2026.xls')
    expect(wrapper.text()).toContain('余额表_2026.xls')
    expect(wrapper.text()).toContain('已导入')
    expect(wrapper.text()).toContain('凭证数量')
    expect(wrapper.text()).toContain('1060')
  })
})

async function selectFile(wrapper, selector, file, index = 0) {
  const input = wrapper.findAll(selector)[index]
  Object.defineProperty(input.element, 'files', {
    configurable: true,
    value: [file],
  })
  await input.trigger('change')
}
