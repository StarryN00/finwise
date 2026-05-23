import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'RulesView.vue'), 'utf8')

describe('RulesView', () => {
  it('shows and saves business types as Chinese labels', () => {
    expect(source).toContain('businessTypeLabel')
    expect(source).toContain("AI_FALLBACK_RULE: '需要规则匹配'")
    expect(source).toContain('银行手续费 / 咨询服务 / 销售收入')
    expect(source).toContain('suggested_business_type: form.businessType.trim()')
    expect(source).not.toContain('suggested_business_type: form.businessType.trim().toUpperCase()')
    expect(source).not.toContain('BANK_FEE / CONSULTING_SERVICE')
  })
})
