import { defineStore } from 'pinia'

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    currentPeriod: '2026-05',
    activeOrganization: '默认代账机构',
    enterprises: [
      {
        id: 'ent-001',
        name: '苏州样例科技有限公司',
        taxpayerType: '一般纳税人',
        latestMonth: '2026-05',
        dataStatus: 'PENDING_CONFIRMATION',
        pendingConfirmations: 3,
        reportStatus: 'READY_TO_EXPORT',
      },
      {
        id: 'ent-002',
        name: '昆山精密制造有限公司',
        taxpayerType: '一般纳税人',
        latestMonth: '2026-05',
        dataStatus: 'CONFIRMED',
        pendingConfirmations: 0,
        reportStatus: 'READY_TO_EXPORT',
      },
      {
        id: 'ent-003',
        name: '吴中贸易有限公司',
        taxpayerType: '小规模纳税人',
        latestMonth: '2026-05',
        dataStatus: 'PENDING_IMPORT',
        pendingConfirmations: 5,
        reportStatus: 'DATA_INSUFFICIENT',
      },
    ],
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
    accountRows: [
      { type: '流水', date: '2026-05-12', summary: '收到货款', status: 'CONFIRMED', confidence: 95, businessType: '主营业务收入', amount: '113,000.00', tax: '13,000.00' },
      { type: '发票', date: '2026-05-10', summary: '销项发票 OUT-1', status: 'CONFIRMED', confidence: 95, businessType: '销项收入', amount: '100,000.00', tax: '13,000.00' },
      { type: '流水', date: '2026-05-20', summary: '银行手续费', status: 'PENDING_CONFIRMATION', confidence: 80, businessType: '手续费', amount: '25.00', tax: '0.00' },
    ],
    missingChecklist: [
      { label: '银行流水', done: true },
      { label: '销项明细', done: true },
      { label: '进项明细', done: true },
      { label: '人工确认', done: false },
      { label: '健康报告数据', done: false },
    ],
  }),
})
