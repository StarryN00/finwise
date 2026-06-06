import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'EnterpriseDetailView.vue'), 'utf8')

describe('EnterpriseDetailView', () => {
  it('renders enterprise profile, initial data, and latest monthly package sections', () => {
    expect(source).toContain('useRoute')
    expect(source).toContain('enterpriseId')
    expect(source).toContain('基础信息')
    expect(source).toContain('营业执照编号')
    expect(source).toContain('补充信息')
    expect(source).toContain('期初数据导入')
    expect(source).toContain('最近工作包')
    expect(source).toContain('workspace.workPackages')
    expect(source).toContain('goAccountDetails')
  })

  it('renders technology qualification profile and review actions', () => {
    expect(source).toContain('科技资质画像')
    expect(source).toContain('technologyProfile')
    expect(source).toContain('confirmTechnologyTag')
    expect(source).toContain('rejectTechnologyTag')
    expect(source).toContain('证据')
    expect(source).toContain('科技型企业认定')
    expect(source).toContain('QCC_TECH_CERTIFICATION')
    expect(source).toContain('QCC_INTELLECTUAL_PROPERTY')
    expect(source).toContain('导入企查查科创分文本')
    expect(source).toContain('qichachaTextDialog')
    expect(source).toContain('submitQichachaText')
    expect(source).toContain('qichacha_innovation_text')
  })
})
