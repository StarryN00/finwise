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
  accountSubjects: {
    list: (enterpriseId) => apiClient.get(`/enterprises/${enterpriseId}/account-subjects`),
    initialize: (enterpriseId) => apiClient.post(`/enterprises/${enterpriseId}/account-subjects/initialize`),
  },
  technologyProfile: {
    get: (enterpriseId) => apiClient.get(`/enterprises/${enterpriseId}/technology-profile`),
    upsert: (enterpriseId, payload) => apiClient.post(`/enterprises/${enterpriseId}/technology-profile/scan-results`, payload),
    confirmTag: (tagId) => apiClient.post(`/technology-tags/${tagId}/confirm`),
    rejectTag: (tagId) => apiClient.post(`/technology-tags/${tagId}/reject`),
  },
  technologyScanJobs: {
    create: (payload) => apiClient.post('/technology-scan-jobs', payload),
    list: () => apiClient.get('/technology-scan-jobs'),
    get: (jobId) => apiClient.get(`/technology-scan-jobs/${jobId}`),
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
  historicalImports: {
    importGbt24589: (enterpriseId, formData) => apiClient.post(`/enterprises/${enterpriseId}/historical-imports/gbt24589`, formData),
  },
  matching: {
    run: (packageId) => apiClient.post(`/monthly-packages/${packageId}/matching/run`),
    runAi: (packageId) => apiClient.post(`/monthly-packages/${packageId}/matching/ai-run`, undefined, { timeout: AI_REQUEST_TIMEOUT_MS }),
    confirmMatch: (matchId) => apiClient.post(`/matches/${matchId}/confirm`),
    confirmLine: (lineId, payload) => apiClient.post(`/accounting-lines/${lineId}/confirm`, payload),
    confirmUnmatched: (packageId, payload) => apiClient.post(`/monthly-packages/${packageId}/confirm-unmatched`, payload),
  },
  vouchers: {
    list: (packageId) => apiClient.get(`/monthly-packages/${packageId}/vouchers`),
    generate: (packageId) => apiClient.post(`/monthly-packages/${packageId}/vouchers/generate`),
    confirm: (voucherId, payload) => apiClient.post(`/vouchers/${voucherId}/confirm`, payload),
    reject: (voucherId, payload) => apiClient.post(`/vouchers/${voucherId}/reject`, payload),
    reopen: (voucherId, payload) => apiClient.post(`/vouchers/${voucherId}/reopen`, payload),
    rematchCandidates: (voucherId) => apiClient.get(`/vouchers/${voucherId}/rematch-candidates`),
    rematch: (voucherId, payload) => apiClient.post(`/vouchers/${voucherId}/rematch`, payload),
    adjustTreatment: (voucherId, payload) => apiClient.post(`/vouchers/${voucherId}/treatment-adjustment`, payload),
  },
  sourceLedgers: {
    bank: (packageId) => apiClient.get(`/monthly-packages/${packageId}/bank-ledger`),
    invoices: (packageId) => apiClient.get(`/monthly-packages/${packageId}/invoice-ledger`),
    summary: (packageId) => apiClient.get(`/monthly-packages/${packageId}/voucher-ledger-summary`),
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
    downloadHealthPdfUrl: (reportId) => `/api/reports/${reportId}/pdf`,
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
