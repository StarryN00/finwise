import { createRouter, createWebHistory } from 'vue-router'
import { api } from '../api/client'
import { getAuthToken } from '../auth/session'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { public: true, publicLayout: true },
  },
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

let authStatusPromise = null

async function getAuthEnabled() {
  if (!authStatusPromise) {
    authStatusPromise = api.auth.status()
      .then((response) => Boolean(response.data?.enabled))
      .catch(() => true)
  }
  return authStatusPromise
}

router.beforeEach(async (to) => {
  const authEnabled = await getAuthEnabled()
  if (!authEnabled) {
    if (to.path === '/login') {
      return { path: '/' }
    }
    return true
  }

  if (to.meta.public) {
    if (to.path === '/login' && getAuthToken()) {
      return typeof to.query.redirect === 'string' ? to.query.redirect : '/'
    }
    return true
  }

  if (!getAuthToken()) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  return true
})
