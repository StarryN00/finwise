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
})
