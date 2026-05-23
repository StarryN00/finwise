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
})
