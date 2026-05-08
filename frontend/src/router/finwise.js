import { useRouter } from 'vue-router'

const router = useRouter()

export const finwiseRouter = {
  isAuthRoute(path) {
    return ['/login'].includes(path)
  },

  buildRouterConfig(layoutComponent) {
    return [
      {
        path: '/login',
        name: 'Login',
        component: () => import('@/views/LoginView.vue'),
        meta: { requiresAuth: false }
      },
      {
        path: '/',
        component: layoutComponent,
        meta: { requiresAuth: true },
        children: [
          {
            path: '',
            name: 'Dashboard',
            component: () => import('@/views/DashboardView.vue')
          },
          {
            path: 'enterprises',
            name: 'Enterprises',
            component: () => import('@/views/enterprises/index.vue')
          },
          {
            path: 'invoices',
            name: 'Invoices',
            component: () => import('@/views/invoices/index.vue')
          },
          {
            path: 'reports',
            name: 'Reports',
            component: () => import('@/views/reports/index.vue')
          },
          {
            path: 'financing',
            name: 'Financing',
            component: () => import('@/views/financing/index.vue')
          }
        ]
      }
    ]
  }
}

export default finwiseRouter