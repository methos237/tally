import { createRouter, createWebHistory } from 'vue-router'

import { useSession } from '@/stores/session'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    { path: '/', name: 'home', component: () => import('@/views/HomeView.vue') },
  ],
})

router.beforeEach(async (to) => {
  const session = useSession()
  if (!session.loaded) await session.load()
  if (to.name !== 'login' && !session.current)
    return { name: 'login', query: { next: to.fullPath } }
  if (to.name === 'login' && session.current) return { name: 'home' }
})

export default router
