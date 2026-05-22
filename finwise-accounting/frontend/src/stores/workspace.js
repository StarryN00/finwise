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
  },
})
