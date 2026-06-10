import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'EnterpriseListView.vue'), 'utf8')

describe('EnterpriseListView', () => {
  it('opens enterprise detail from the roster', () => {
    expect(source).toContain('openEnterpriseDetail')
    expect(source).toContain("router.push(`/enterprises/${row.id}`)")
    expect(source).toContain('企业名称')
    expect(source).toContain('enterprise-name-link')
  })

  it('shows technology profile status and key tags on the roster', () => {
    expect(source).toContain('科技画像')
    expect(source).toContain('technologyProfileStatus')
    expect(source).toContain('technologyTags')
    expect(source).toContain('ipSummary')
    expect(source).toContain('formatTechnologyStatus')
    expect(source).toContain('批量扫描科技画像')
    expect(source).toContain('technologyScanJobs')
    expect(source).toContain('createTechnologyScanJob')
    expect(source).toContain('scanJobDrawerVisible')
  })

  it('requires confirmation before deleting an enterprise and passes a business id to the API', () => {
    expect(source).toContain('ElMessageBox.confirm')
    expect(source).toContain('确认删除企业')
    expect(source).toContain('不可恢复')
    expect(source).toContain('@click.stop="confirmDeleteEnterprise(row)"')
    expect(source).toContain('api.enterprises.remove(enterpriseId)')
    expect(source).toContain('企业及关联数据已删除')
    expect(source).toContain('formatEnterpriseDeleteError')
    expect(source).toContain('企业删除失败')
  })
})
