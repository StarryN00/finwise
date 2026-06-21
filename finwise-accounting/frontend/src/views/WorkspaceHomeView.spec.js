import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'WorkspaceHomeView.vue'), 'utf8')

describe('WorkspaceHomeView onboarding', () => {
  it('renders a state-driven opening workflow instead of a plain empty table', () => {
    expect(source).toContain('开账准备')
    expect(source).toContain('第 1 步：建立企业档案')
    expect(source).toContain('第 2 步：导入期初/历史账套')
    expect(source).toContain('第 3 步：创建月度工作包')
    expect(source).toContain('第 4 步：导入当月资料')
    expect(source).toContain('第 5 步：AI预处理与凭证确认')
    expect(source).toContain('第 6 步：输出申报与报告')
    expect(source).toContain('primaryGuidance')
    expect(source).toContain('onboardingSteps')
  })

  it('links each onboarding step to the real operating surface', () => {
    expect(source).toContain("'/enterprises/init'")
    expect(source).toContain("'/historical-import'")
    expect(source).toContain("'/monthly-workspace'")
    expect(source).toContain("'/vouchers'")
    expect(source).toContain("'/output-center'")
    expect(source).toContain("'/ledgers'")
  })

  it('shows an actionable empty state for a new production tenant', () => {
    expect(source).toContain('先创建第一家企业')
    expect(source).toContain('el-empty')
    expect(source).toContain('handlePackageAction')
  })
})
