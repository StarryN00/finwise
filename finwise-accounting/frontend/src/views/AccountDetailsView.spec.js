import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'AccountDetailsView.vue'), 'utf8')

describe('AccountDetailsView', () => {
  it('renders a unified account detail table with party and completeness fields', () => {
    expect(source).toContain('完整性')
    expect(source).toContain('PackageContextBar')
    expect(source).toContain('当前操作主体')
    expect(source).toContain('directionType')
    expect(source).toContain('transactionCounterparty')
    expect(source).toContain('invoiceCounterparty')
    expect(source).toContain('交易对方')
    expect(source).toContain('发票对方')
    expect(source).toContain('缺失发票')
    expect(source).toContain('缺失转账')
    expect(source).toContain('sourceCompleteness')
    expect(source).toContain('备注')
    expect(source).toContain('AI 智能匹配')
    expect(source).toContain('account-toolbar__actions')
    expect(source).toContain('account-table-scroll')
    expect(source).toContain('scroll-affordance')
    expect(source).toContain('overflow-x: auto')
    expect(source).toContain('min-width: 1120px')
    expect(source).toContain('ai-progress-panel')
    expect(source).toContain('el-progress')
    expect(source).toContain('aiProgress')
    expect(source).toContain("result?.aiStatus === 'UNAVAILABLE'")
    expect(source).toContain('runAiMatching')
    expect(source).not.toContain('付款方')
    expect(source).not.toContain('收款方')
    expect(source).not.toContain('销售方')
    expect(source).not.toContain('购买方')
    expect(source).not.toContain('流水视图')
    expect(source).not.toContain('发票视图')
  })
})
