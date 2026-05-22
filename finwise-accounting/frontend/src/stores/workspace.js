import { defineStore } from 'pinia'

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    currentPeriod: '2026-05',
    activeOrganization: '默认代账机构',
    metrics: [
      { label: '待处理企业', value: '18', subtext: '7 家待导入资料', tone: 'warning' },
      { label: '本月已确认', value: '42', subtext: '账目明细已确认', tone: 'success' },
      { label: '可导出申报', value: '9', subtext: '申报草稿可下载', tone: 'primary' },
    ],
    workPackages: [
      { company: '苏州样例科技有限公司', period: '2026-05', status: 'PENDING_CONFIRMATION', pending: 3, tax: '7,800.00' },
      { company: '昆山精密制造有限公司', period: '2026-05', status: 'READY_TO_EXPORT', pending: 0, tax: '12,430.00' },
      { company: '吴中贸易有限公司', period: '2026-05', status: 'DATA_INSUFFICIENT', pending: 5, tax: '-' },
    ],
  }),
})
