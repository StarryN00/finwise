import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'PackageContextBar.vue'), 'utf8')

describe('PackageContextBar', () => {
  it('keeps enterprise and accounting period as two separate selectors', () => {
    expect(source).toContain('v-model="selectedEnterpriseId"')
    expect(source).toContain('placeholder="选择企业主体"')
    expect(source).toContain('v-model="selectedPeriodPackageId"')
    expect(source).toContain('placeholder="选择工作期间"')
    expect(source).toContain('enterpriseOptions')
    expect(source).toContain('periodOptions')
    expect(source).not.toContain('搜索企业或期间')
    expect(source).not.toContain('`${item.company} · ${item.period}`')
  })

  it('builds enterprise selector options from initialized enterprises before monthly packages exist', () => {
    expect(source).toContain('for (const item of workspace.enterprises)')
    expect(source).toContain("options.push({ enterpriseId: item.id, company: item.name })")
    expect(source.indexOf('for (const item of workspace.enterprises)')).toBeLessThan(
      source.indexOf('for (const item of workspace.workPackages)'),
    )
  })
})
