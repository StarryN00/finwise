import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'AppLayout.vue'), 'utf8')
const routerSource = readFileSync(resolve(__dirname, '../router/index.js'), 'utf8')

function countOccurrences(text, value) {
  return text.match(new RegExp(value, 'g'))?.length ?? 0
}

function countNavEntries(text, label) {
  return text.match(new RegExp(`\\{\\s*label:\\s*'${label}',\\s*path:`, 'g'))?.length ?? 0
}

function navEntryPattern(label, path) {
  return new RegExp(`\\{\\s*label:\\s*'${label}',\\s*path:\\s*'${path}'\\s*\\}`)
}

function navGroupPattern(label) {
  return new RegExp(`\\{\\s*label:\\s*'${label}',\\s*children:\\s*\\[`)
}

function routePattern(path) {
  return new RegExp(`\\{[\\s\\S]*?path:\\s*'${path}'[\\s\\S]*?component:\\s*\\(\\)\\s*=>\\s*import\\(`)
}

describe('AppLayout navigation', () => {
  it('groups sidebar navigation by operator workflow', () => {
    expect(source).toMatch(navGroupPattern('客户管理'))
    expect(source).toMatch(navGroupPattern('月度作业'))
    expect(source).toMatch(navGroupPattern('凭证与账簿'))
    expect(source).toMatch(navGroupPattern('申报与报告'))
    expect(source).toMatch(navGroupPattern('基础设置'))
    expect(source).toMatch(/<section[\s\S]*v-for="group in navGroups"[\s\S]*class="app-nav__group"/)
    expect(source).toMatch(/<router-link[\s\S]*v-for="item in group\.children"[\s\S]*:to="item\.path"[\s\S]*>/)
  })

  it('keeps all business routes reachable from grouped navigation', () => {
    expect(source).toMatch(navEntryPattern('工作台', '/'))
    expect(source).toMatch(navEntryPattern('企业名册', '/enterprises'))
    expect(source).toMatch(navEntryPattern('月度工作包', '/monthly-workspace'))
    expect(source).toMatch(navEntryPattern('账目明细', '/account-details'))
    expect(source).toMatch(navEntryPattern('资金流水', '/bank-ledger'))
    expect(source).toMatch(navEntryPattern('发票台账', '/invoice-ledger'))
    expect(source).toMatch(navEntryPattern('凭证生成', '/vouchers'))
    expect(source).toMatch(navEntryPattern('凭证管理', '/voucher-management'))
    expect(source).toMatch(navEntryPattern('账簿', '/ledgers'))
    expect(source).toMatch(navEntryPattern('历史账套导入', '/historical-import'))
    expect(source).toMatch(navEntryPattern('输出中心', '/output-center'))
    expect(source).toMatch(navEntryPattern('科目设置', '/account-subjects'))
    expect(source).toMatch(navEntryPattern('规则设置', '/rules'))
  })

  it('renders each accounting workspace nav label once', () => {
    expect(countNavEntries(source, '科目设置')).toBe(1)
    expect(countNavEntries(source, '凭证生成')).toBe(1)
    expect(countNavEntries(source, '凭证管理')).toBe(1)
    expect(countNavEntries(source, '账簿')).toBe(1)
  })

  it('keeps accounting workspace nav paths registered in the router', () => {
    expect(routerSource).toMatch(routePattern('/account-subjects'))
    expect(routerSource).toMatch(routePattern('/vouchers'))
    expect(routerSource).toMatch(routePattern('/voucher-management'))
    expect(routerSource).toMatch(routePattern('/ledgers'))
  })

  it('exposes authenticated password change with a real API call and forced re-login', () => {
    expect(source).toContain("import { api } from '../api/client'")
    expect(source).toContain('修改密码')
    expect(source).toContain('openPasswordDialog')
    expect(source).toContain('submitPasswordChange')
    expect(source).toContain('api.auth.changePassword')
    expect(source).toContain('old_password: passwordForm.oldPassword')
    expect(source).toContain('new_password: passwordForm.newPassword')
    expect(source).toContain('clearAuthSession()')
    expect(source).toContain("router.replace('/login')")
  })
})
