import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'workspace',
    component: () => import('../views/WorkspaceHomeView.vue'),
  },
  {
    path: '/enterprises',
    name: 'enterprises',
    component: () => import('../views/EnterpriseListView.vue'),
  },
  {
    path: '/enterprises/init',
    name: 'enterprise-init',
    component: () => import('../views/EnterpriseInitView.vue'),
  },
  {
    path: '/enterprises/:enterpriseId',
    name: 'enterprise-detail',
    component: () => import('../views/EnterpriseDetailView.vue'),
  },
  {
    path: '/monthly-workspace',
    name: 'monthly-workspace',
    component: () => import('../views/MonthlyWorkspaceView.vue'),
  },
  {
    path: '/account-details',
    name: 'account-details',
    component: () => import('../views/AccountDetailsView.vue'),
  },
  {
    path: '/bank-ledger',
    name: 'bank-ledger',
    component: () => import('../views/BankLedgerView.vue'),
  },
  {
    path: '/invoice-ledger',
    name: 'invoice-ledger',
    component: () => import('../views/InvoiceLedgerView.vue'),
  },
  {
    path: '/account-subjects',
    name: 'account-subjects',
    component: () => import('../views/AccountSubjectsView.vue'),
  },
  {
    path: '/historical-import',
    name: 'historical-import',
    component: () => import('../views/HistoricalImportView.vue'),
  },
  {
    path: '/vouchers',
    name: 'vouchers',
    component: () => import('../views/VoucherWorkbenchView.vue'),
  },
  {
    path: '/voucher-management',
    name: 'voucher-management',
    component: () => import('../views/VoucherManagementView.vue'),
  },
  {
    path: '/ledgers',
    name: 'ledgers',
    component: () => import('../views/LedgerView.vue'),
  },
  {
    path: '/output-center',
    name: 'output-center',
    component: () => import('../views/OutputCenterView.vue'),
  },
  {
    path: '/rules',
    name: 'rules',
    component: () => import('../views/RulesView.vue'),
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
