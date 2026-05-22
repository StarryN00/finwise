import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'AccountDetailsView.vue'), 'utf8')

describe('AccountDetailsView', () => {
  it('renders a unified account detail table with party and completeness fields', () => {
    expect(source).toContain('统一视图')
    expect(source).toContain('缺失发票')
    expect(source).toContain('缺失转账')
    expect(source).toContain('sourceCompleteness')
    expect(source).toContain('付款方')
    expect(source).toContain('收款方')
    expect(source).toContain('销售方')
    expect(source).toContain('购买方')
    expect(source).toContain('备注')
    expect(source).toContain('AI 智能匹配')
    expect(source).toContain('runAiMatching')
    expect(source).not.toContain('流水视图')
    expect(source).not.toContain('发票视图')
  })
})
