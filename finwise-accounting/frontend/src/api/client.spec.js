import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(__dirname, 'client.js'), 'utf8')

describe('api client', () => {
  it('uses extended timeouts for AI operations that can exceed the default request budget', () => {
    expect(source).toContain('AI_REQUEST_TIMEOUT_MS')
    expect(source).toContain('runAi: (packageId) => apiClient.post(`/monthly-packages/${packageId}/matching/ai-run`, undefined, { timeout: AI_REQUEST_TIMEOUT_MS })')
    expect(source).toContain('preprocess: (packageId) => apiClient.post(`/monthly-packages/${packageId}/vouchers/preprocess`, undefined, { timeout: AI_REQUEST_TIMEOUT_MS })')
    expect(source).toContain('generateHealth: (packageId) => apiClient.post(`/monthly-packages/${packageId}/reports/health`, undefined, { timeout: AI_REQUEST_TIMEOUT_MS })')
    expect(source).toContain('downloadHealthPdfUrl: (reportId) => `/api/reports/${reportId}/pdf`')
  })

  it('wires read-only accounting ledger endpoints', () => {
    expect(source).toContain('ledgers')
    expect(source).toContain('summary: (packageId) => apiClient.get(`/monthly-packages/${packageId}/ledgers/summary`)')
    expect(source).toContain('accounts: (packageId) => apiClient.get(`/monthly-packages/${packageId}/ledgers/accounts`)')
    expect(source).toContain('journal: (packageId) => apiClient.get(`/monthly-packages/${packageId}/ledgers/journal`)')
    expect(source).toContain('general: (packageId) => apiClient.get(`/monthly-packages/${packageId}/ledgers/general`)')
    expect(source).toContain('detail: (packageId, accountCode) => apiClient.get(`/monthly-packages/${packageId}/ledgers/detail`, { params: { account_code: accountCode } })')
    expect(source).toContain('trialBalance: (packageId) => apiClient.get(`/monthly-packages/${packageId}/ledgers/trial-balance`)')
  })

  it('wires enterprise delete endpoint with an explicit business id', () => {
    expect(source).toContain('remove: (enterpriseId) => apiClient.delete(`/enterprises/${enterpriseId}`)')
  })

  it('wires login endpoints and bearer token handling', () => {
    expect(source).toContain("import { clearAuthSession, getAuthToken } from '../auth/session'")
    expect(source).toContain('apiClient.interceptors.request.use')
    expect(source).toContain('config.headers.Authorization = `Bearer ${token}`')
    expect(source).toContain('apiClient.interceptors.response.use')
    expect(source).toContain('clearAuthSession()')
    expect(source).toContain("status: () => apiClient.get('/auth/status')")
    expect(source).toContain("login: (payload) => apiClient.post('/auth/login', payload)")
    expect(source).toContain("me: () => apiClient.get('/auth/me')")
    expect(source).toContain("changePassword: (payload) => apiClient.post('/auth/change-password', payload)")
  })
})
