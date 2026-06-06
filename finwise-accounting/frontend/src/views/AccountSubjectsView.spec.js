import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const viewSource = readFileSync(resolve(__dirname, 'AccountSubjectsView.vue'), 'utf8')
const clientSource = readFileSync(resolve(__dirname, '../api/client.js'), 'utf8')
const routerSource = readFileSync(resolve(__dirname, '../router/index.js'), 'utf8')

describe('AccountSubjectsView', () => {
  it('wires the account subject settings page, API client, and route', () => {
    expect(viewSource).toContain('科目设置')
    expect(viewSource).toContain('初始化科目')
    expect(viewSource).toContain('api.accountSubjects.initialize')
    expect(viewSource).toContain('api.accountSubjects.list')
    expect(viewSource).toContain('allow_voucher')
    expect(viewSource).toContain('subjects-table-scroll')
    expect(viewSource).toContain('width: 100%')
    expect(viewSource).toContain('min-width="150"')
    expect(viewSource).toContain('min-width: 750px')
    expect(viewSource).toContain('categoryLabel(row.category)')
    expect(viewSource).toContain('balanceDirectionLabel(row.normal_balance)')
    expect(viewSource).toContain("ASSET: '资产'")
    expect(viewSource).toContain("DEBIT: '借方'")
    expect(viewSource).toContain('let subjectLoadRequestId = 0')
    expect(viewSource).toContain('const requestId = ++subjectLoadRequestId')
    expect(viewSource).toContain('isStaleSubjectLoad(requestId, enterpriseId)')
    expect(viewSource).toContain('enterpriseId !== selectedEnterpriseId.value')
    expect(viewSource).not.toContain('onMounted')
    expect(clientSource).toContain('accountSubjects')
    expect(clientSource).toContain('/enterprises/${enterpriseId}/account-subjects')
    expect(clientSource).toContain('/enterprises/${enterpriseId}/account-subjects/initialize')
    expect(routerSource).toContain('/account-subjects')
  })
})
