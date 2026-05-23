import axios from 'axios'

const AI_REQUEST_TIMEOUT_MS = 120000

export const apiClient = axios.create({
  baseURL: '/api',
  timeout: 20000,
})

export const api = {
  enterprises: {
    list: () => apiClient.get('/enterprises'),
    create: (payload) => apiClient.post('/enterprises', payload),
    initialize: (enterpriseId, payload) => apiClient.post(`/enterprises/${enterpriseId}/initial-snapshot`, payload),
  },
  packages: {
    create: (enterpriseId, payload) => apiClient.post(`/enterprises/${enterpriseId}/monthly-packages`, payload),
  },
  imports: {
    bank: (packageId, formData) => apiClient.post(`/monthly-packages/${packageId}/imports/bank`, formData),
    inputInvoices: (packageId, formData) => apiClient.post(`/monthly-packages/${packageId}/imports/input-invoices`, formData),
    outputInvoices: (packageId, formData) => apiClient.post(`/monthly-packages/${packageId}/imports/output-invoices`, formData),
  },
  initialStatements: {
    parse: (formData) => apiClient.post('/initial-statements/parse', formData),
  },
  matching: {
    run: (packageId) => apiClient.post(`/monthly-packages/${packageId}/matching/run`),
    runAi: (packageId) => apiClient.post(`/monthly-packages/${packageId}/matching/ai-run`, undefined, { timeout: AI_REQUEST_TIMEOUT_MS }),
    confirmMatch: (matchId) => apiClient.post(`/matches/${matchId}/confirm`),
    confirmLine: (lineId, payload) => apiClient.post(`/accounting-lines/${lineId}/confirm`, payload),
    confirmUnmatched: (packageId, payload) => apiClient.post(`/monthly-packages/${packageId}/confirm-unmatched`, payload),
  },
  statements: {
    generate: (packageId) => apiClient.post(`/monthly-packages/${packageId}/statements/generate`),
    viewUrl: (packageId) => `/api/monthly-packages/${packageId}/statements/latest/html`,
  },
  tax: {
    getDraft: (draftId) => apiClient.get(`/tax-drafts/${draftId}`),
    generateVatDraft: (packageId) => apiClient.post(`/monthly-packages/${packageId}/tax/vat-draft`),
    updateDraft: (draftId, payload) => apiClient.patch(`/tax-drafts/${draftId}`, payload),
    exportDraft: (draftId) => apiClient.post(`/tax-drafts/${draftId}/export`, undefined, { responseType: 'blob' }),
    viewDraftUrl: (draftId) => `/api/tax-drafts/${draftId}/html`,
  },
  reports: {
    generateHealth: (packageId) => apiClient.post(`/monthly-packages/${packageId}/reports/health`, undefined, { timeout: AI_REQUEST_TIMEOUT_MS }),
    viewHealthUrl: (reportId) => `/api/reports/${reportId}/html`,
  },
  rules: {
    list: (enterpriseId) => apiClient.get('/rules', { params: enterpriseId ? { enterprise_id: enterpriseId } : {} }),
    create: (payload) => apiClient.post('/rules', payload),
    remove: (ruleId) => apiClient.delete(`/rules/${ruleId}`),
  },
  workspace: {
    snapshot: (packageId) => apiClient.get('/workspace', { params: packageId ? { package_id: packageId } : {} }),
  },
}
