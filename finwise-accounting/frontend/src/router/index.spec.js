import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'index.js'), 'utf8')

describe('router auth guard', () => {
  it('registers the login page as a public route', () => {
    expect(source).toContain("path: '/login'")
    expect(source).toContain('publicLayout: true')
  })

  it('checks backend auth status and redirects protected pages without a token', () => {
    expect(source).toContain('router.beforeEach')
    expect(source).toContain('api.auth.status()')
    expect(source).toContain('getAuthToken()')
    expect(source).toContain("query: { redirect: to.fullPath }")
  })
})
