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

function navItemPattern(label, path) {
  return new RegExp(`\\{\\s*label:\\s*'${label}',\\s*path:\\s*'${path}'\\s*\\}`)
}

function routePattern(path) {
  return new RegExp(`\\{[\\s\\S]*?path:\\s*'${path}'[\\s\\S]*?component:\\s*\\(\\)\\s*=>\\s*import\\(`)
}

describe('AppLayout navigation', () => {
  it('links accounting workspace nav entries through router-link', () => {
    expect(source).toMatch(navItemPattern('科目设置', '/account-subjects'))
    expect(source).toMatch(navItemPattern('凭证生成', '/vouchers'))
    expect(source).toMatch(navItemPattern('凭证管理', '/voucher-management'))
    expect(source).toMatch(navItemPattern('账簿', '/ledgers'))
    expect(source).toMatch(/<router-link[\s\S]*v-for="item in navItems"[\s\S]*:to="item\.path"[\s\S]*>/)
  })

  it('renders each accounting workspace nav label once', () => {
    expect(countOccurrences(source, '科目设置')).toBe(1)
    expect(countOccurrences(source, '凭证生成')).toBe(1)
    expect(countOccurrences(source, '凭证管理')).toBe(1)
    expect(countOccurrences(source, '账簿')).toBe(1)
  })

  it('keeps accounting workspace nav paths registered in the router', () => {
    expect(routerSource).toMatch(routePattern('/account-subjects'))
    expect(routerSource).toMatch(routePattern('/vouchers'))
    expect(routerSource).toMatch(routePattern('/voucher-management'))
    expect(routerSource).toMatch(routePattern('/ledgers'))
  })
})
