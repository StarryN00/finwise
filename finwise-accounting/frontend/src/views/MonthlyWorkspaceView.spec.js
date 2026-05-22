import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'MonthlyWorkspaceView.vue'), 'utf8')

describe('MonthlyWorkspaceView', () => {
  it('provides upload actions for bank, input invoices, and output invoices', () => {
    expect(source).toContain('uploadBankStatement')
    expect(source).toContain('uploadInputInvoices')
    expect(source).toContain('uploadOutputInvoices')
    expect(source).toContain('银行流水')
    expect(source).toContain('进项明细')
    expect(source).toContain('销项明细')
  })

  it('renders the monthly workflow as a status timeline', () => {
    expect(source).toContain('workflow-timeline')
    expect(source).toContain("step.status === 'done'")
    expect(source).toContain("step.status === 'current'")
    expect(source).toContain("step.status === 'todo'")
  })

  it('shows aligned document rows and persistent upload errors', () => {
    expect(source).toContain('upload-row')
    expect(source).toContain('upload-item-error')
    expect(source).toContain('formatUploadError')
    expect(source).toContain('uploadErrors')
  })

  it('shows the active enterprise context and next workflow actions', () => {
    expect(source).toContain('active-package-context')
    expect(source).toContain('当前处理企业')
    expect(source).toContain('next-action-panel')
    expect(source).toContain('nextActions')
    expect(source).toContain('generateVatDraft')
    expect(source).toContain('generateHealthReport')
  })
})
