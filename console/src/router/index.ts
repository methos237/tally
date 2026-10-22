import { createRouter, createWebHistory } from 'vue-router'

import HealthView from '@/views/HealthView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [{ path: '/', name: 'health', component: HealthView }],
})

export default router
