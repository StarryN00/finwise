import { createRouter, createWebHistory } from 'vue-router'
import Layout from '@/layout/index.vue'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/',
    component: Layout,
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/index.vue')
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

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.requiresAuth && !token) {
    next('/login')
  } else if (to.path === '/login' && token) {
    next('/')
  } else {
    next()
  }
})

export default router