import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '../stores/auth'
import AdminPage from '../views/AdminPage.vue'
import AdminAgentsPage from '../views/AdminAgentsPage.vue'
import AdminUsersPage from '../views/AdminUsersPage.vue'
import AgentsPage from '../views/AgentsPage.vue'
import ChatPage from '../views/ChatPage.vue'
import DashboardPage from '../views/DashboardPage.vue'
import FilesPage from '../views/FilesPage.vue'
import LoginPage from '../views/LoginPage.vue'
import RegisterPage from '../views/RegisterPage.vue'
import RunsPage from '../views/RunsPage.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: DashboardPage,
      meta: { requiresAuth: true },
    },
    {
      path: '/agents',
      name: 'agents',
      component: AgentsPage,
      meta: { requiresAuth: true },
    },
    {
      path: '/agents/:agentCode/chat',
      name: 'agent-chat',
      component: ChatPage,
      meta: { requiresAuth: true },
    },
    {
      path: '/runs',
      name: 'runs',
      component: RunsPage,
      meta: { requiresAuth: true },
    },
    {
      path: '/files',
      name: 'files',
      component: FilesPage,
      meta: { requiresAuth: true },
    },
    {
      path: '/login',
      name: 'login',
      component: LoginPage,
      meta: { guestOnly: true },
    },
    {
      path: '/register',
      name: 'register',
      component: RegisterPage,
      meta: { guestOnly: true },
    },
    {
      path: '/admin',
      name: 'admin',
      component: AdminPage,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: '/admin/users',
      name: 'admin-users',
      component: AdminUsersPage,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: '/admin/agents',
      name: 'admin-agents',
      component: AdminAgentsPage,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
  ],
})

router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  if (authStore.token && !authStore.user) {
    try {
      await authStore.fetchCurrentUser()
    } catch {
      authStore.logout()
    }
  }

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    return {
      name: 'login',
      query: { redirect: to.fullPath },
    }
  }

  if (to.meta.requiresAdmin && !authStore.isAdmin) {
    return { name: 'dashboard' }
  }

  if (to.meta.guestOnly && authStore.isAuthenticated) {
    return { name: 'dashboard' }
  }

  return true
})

export default router
