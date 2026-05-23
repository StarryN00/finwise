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
})
