import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'OutputCenterView.vue'), 'utf8')

describe('OutputCenterView', () => {
  it('lets operators switch the active enterprise package before generating outputs', () => {
    expect(source).toContain('PackageContextBar')
    expect(source).toContain('status-label="输出状态"')
    expect(source).toContain(':status-value="outputStateText"')
    expect(source).not.toContain('operation-context')
  })

  it('shows online report viewing actions', () => {
    expect(source).toContain('在线查看')
    expect(source).toContain('openStatementView')
    expect(source).toContain('openHealthReportView')
  })

  it('keeps tax draft generation, review, and export in one filing module', () => {
    expect(source).toContain('辅助申报表')
    expect(source).toContain('生成申报草稿')
    expect(source).toContain('查看/修改草稿')
    expect(source).toContain('下载申报 Excel')
    expect(source).toContain('openTaxDraftEditor')
    expect(source).toContain('saveTaxDraftEdits')
    expect(source).toContain('申报草稿核对')
    expect(source).not.toContain('导出申报文件')
  })
})
