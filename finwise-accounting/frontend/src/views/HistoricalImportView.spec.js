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
    expect(source).toContain('序时账')
    expect(source).toContain('余额表')
    expect(source).toContain('导入历史账套')
    expect(source).toContain('导入批次')
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
    const wrapper = mount(HistoricalImportView, {
      global: {
        stubs: {
          DataTableShell: { template: '<section><slot /></section>' },
          PackageContextBar: { template: '<div />' },
          ElButton: { template: '<button type="button" @click="$emit(`click`)"><slot /></button>' },
          ElForm: { template: '<form><slot /></form>' },
          ElFormItem: { template: '<label><slot /></label>' },
          ElInputNumber: { template: '<input />' },
          ElOption: true,
          ElSelect: { template: '<select><slot /></select>' },
          ElTable: { props: ['data'], template: '<table><tbody><tr v-for="row in data" :key="row.label"><td>{{ row.label }}</td><td>{{ row.value }}</td></tr></tbody></table>' },
          ElTableColumn: true,
          ElTag: { template: '<span><slot /></span>' },
        },
      },
    })

    await selectFile(wrapper, 'input[accept=".xls,.xlsx"]', new File(['ledger'], '序时账_2025.xls'))
    await selectFile(wrapper, 'input[accept=".xls,.xlsx"]', new File(['balance'], '余额表_2025.xls'), 1)
    await wrapper.findAll('button').find((button) => button.text() === '导入历史账套').trigger('click')
    await flushPromises()

    expect(api.historicalImports.importGbt24589).toHaveBeenCalledWith('enterprise-1', expect.any(FormData))
    expect(wrapper.text()).toContain('2025 年历史账套已导入：序时账 4664 行，余额表 297 行')
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
