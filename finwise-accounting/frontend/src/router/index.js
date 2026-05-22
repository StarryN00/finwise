import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'workspace',
    component: () => import('../views/WorkspaceHomeView.vue'),
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
