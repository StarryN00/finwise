import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'EnterpriseInitView.vue'), 'utf8')

describe('EnterpriseInitView', () => {
  it('uses dropdowns for industry, province, and city selection', () => {
    expect(source).toContain('v-model="form.industry"')
    expect(source).toContain('v-model="form.province"')
    expect(source).toContain('v-model="form.city"')
    expect(source).toContain('v-for="industry in industryOptions"')
    expect(source).toContain('v-for="province in provinceOptions"')
    expect(source).toContain('v-for="city in cityOptions"')
  })

  it('parses uploaded initial statements and backfills key subjects', () => {
    expect(source).toContain(':on-change="parseBalanceSheet"')
    expect(source).toContain(':on-change="parseIncomeStatement"')
    expect(source).toContain("api.initialStatements.parse(formData)")
    expect(source).toContain("form.assetsTotal = data.data['资产总计']")
    expect(source).toContain("form.revenue = data.data['营业收入']")
  })

  it('shows Chinese save conflict guidance instead of raw backend English', () => {
    expect(source).toContain('formatEnterpriseSaveError(error)')
    expect(source).toContain('该统一社会信用代码已存在，请检查是否已保存过该企业。')
    expect(source).toContain('企业档案可能已经创建成功')
  })
})
