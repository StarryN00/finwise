import axios from 'axios'

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
  matching: {
    run: (packageId) => apiClient.post(`/monthly-packages/${packageId}/matching/run`),
    confirmMatch: (matchId) => apiClient.post(`/matches/${matchId}/confirm`),
    confirmLine: (lineId, payload) => apiClient.post(`/accounting-lines/${lineId}/confirm`, payload),
    confirmUnmatched: (packageId, payload) => apiClient.post(`/monthly-packages/${packageId}/confirm-unmatched`, payload),
  },
  statements: {
    generate: (packageId) => apiClient.post(`/monthly-packages/${packageId}/statements/generate`),
  },
  tax: {
    generateVatDraft: (packageId) => apiClient.post(`/monthly-packages/${packageId}/tax/vat-draft`),
    exportDraft: (draftId) => apiClient.post(`/tax-drafts/${draftId}/export`, undefined, { responseType: 'blob' }),
  },
  reports: {
    generateHealth: (packageId) => apiClient.post(`/monthly-packages/${packageId}/reports/health`),
  },
  rules: {
    list: (enterpriseId) => apiClient.get('/rules', { params: enterpriseId ? { enterprise_id: enterpriseId } : {} }),
    create: (payload) => apiClient.post('/rules', payload),
    remove: (ruleId) => apiClient.delete(`/rules/${ruleId}`),
  },
  workspace: {
    snapshot: () => apiClient.get('/workspace'),
  },
}
