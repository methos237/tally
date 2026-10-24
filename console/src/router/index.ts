import { createRouter, createWebHistory } from 'vue-router'

import { useSession } from '@/stores/session'

export const pages = [
  {
    path: '/',
    name: 'dashboard',
    label: 'Dashboard',
    component: () => import('@/views/DashboardView.vue'),
  },
  {
    path: '/journal',
    name: 'journal',
    label: 'Journal',
    component: () => import('@/views/JournalView.vue'),
  },
  {
    path: '/accounts',
    name: 'accounts',
    label: 'Accounts',
    component: () => import('@/views/AccountsView.vue'),
  },
  {
    path: '/billing',
    name: 'billing',
    label: 'Billing',
    component: () => import('@/views/BillingView.vue'),
  },
  {
    path: '/webhooks',
    name: 'webhooks',
    label: 'Webhooks',
    component: () => import('@/views/WebhooksView.vue'),
  },
  {
    path: '/reconciliation',
    name: 'reconciliation',
    label: 'Reconciliation',
    component: () => import('@/views/ReconciliationView.vue'),
  },
  {
    path: '/reports',
    name: 'reports',
    label: 'Reports',
    component: () => import('@/views/ReportsView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    ...pages,
  ],
})

router.beforeEach(async (to) => {
  const session = useSession()
  if (!session.loaded) await session.load()
  if (to.name !== 'login' && !session.current)
    return { name: 'login', query: { next: to.fullPath } }
  if (to.name === 'login' && session.current) return { name: 'dashboard' }
})

export default router
