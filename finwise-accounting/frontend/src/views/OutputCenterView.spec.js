import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'OutputCenterView.vue'), 'utf8')

describe('OutputCenterView', () => {
  it('shows active operation context and online report viewing actions', () => {
    expect(source).toContain('operation-context')
    expect(source).toContain('当前操作企业')
    expect(source).toContain('在线查看')
    expect(source).toContain('openStatementView')
    expect(source).toContain('openHealthReportView')
  })
})
