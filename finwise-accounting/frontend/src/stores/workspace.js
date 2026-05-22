import { defineStore } from 'pinia'
import { api } from '../api/client'

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    isLoading: false,
    loadError: '',
    currentPeriod: '',
    activeOrganization: '默认代账机构',
    enterprises: [],
    metrics: [],
    workPackages: [],
    accountRows: [],
    missingChecklist: [],
  }),
  getters: {
    activePackage: (state) => state.workPackages[0] || null,
  },
  actions: {
    async loadWorkspace() {
      this.isLoading = true
      this.loadError = ''
      try {
        const response = await api.workspace.snapshot()
        Object.assign(this, response.data)
      } catch (error) {
        this.loadError = error?.message || '工作台数据加载失败'
      } finally {
        this.isLoading = false
      }
    },
    async createMonthlyPackage(enterpriseId, periodYear, periodMonth) {
      await api.packages.create(enterpriseId, { period_year: periodYear, period_month: periodMonth })
      await this.loadWorkspace()
    },
    async runMatching(packageId) {
      await api.matching.run(packageId)
      await this.loadWorkspace()
    },
    async runAiMatching(packageId) {
      const response = await api.matching.runAi(packageId)
      await this.loadWorkspace()
      return response.data
    },
    async confirmRow(row, payload = {}) {
      if (row.confirmType === 'match') {
        await api.matching.confirmMatch(row.confirmId)
      } else if (row.confirmType === 'accountingLine') {
        await api.matching.confirmLine(row.confirmId, { save_as_rule: Boolean(payload.saveAsRule) })
      } else if (row.confirmType === 'unmatched') {
        await api.matching.confirmUnmatched(row.packageId, {
          source_type: row.sourceType,
          source_id: row.sourceId,
          business_type: payload.businessType,
          save_as_rule: Boolean(payload.saveAsRule),
        })
      } else {
        throw new Error('当前行没有可确认的操作')
      }
      await this.loadWorkspace()
    },
    async generateStatement(packageId) {
      await api.statements.generate(packageId)
      await this.loadWorkspace()
    },
    async generateVatDraft(packageId) {
      await api.tax.generateVatDraft(packageId)
      await this.loadWorkspace()
    },
    async generateHealthReport(packageId) {
      await api.reports.generateHealth(packageId)
      await this.loadWorkspace()
    },
    async exportTaxDraft(draftId) {
      const response = await api.tax.exportDraft(draftId)
      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = '增值税申报草稿.xlsx'
      link.click()
      URL.revokeObjectURL(url)
      await this.loadWorkspace()
    },
  },
})
