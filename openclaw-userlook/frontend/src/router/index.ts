import { createRouter, createWebHistory } from 'vue-router'

import DashboardPage from '../views/DashboardPage.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: DashboardPage,
    },
  ],
})

export default router
