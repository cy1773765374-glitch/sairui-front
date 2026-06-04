<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ChatDotRound,
  Collection,
  DataBoard,
  Expand,
  Files,
  Fold,
  House,
  Management,
  SwitchButton,
  User,
} from '@element-plus/icons-vue'

import { useAppStore } from '../stores/app'
import { useAuthStore } from '../stores/auth'
import sairuiLogo from '../assets/sairui-logo.png'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()
const sidebarCollapsed = ref(localStorage.getItem('sairui:main-sidebar-collapsed') === 'true')
const isDesktop = ref(true)

let mediaQuery: MediaQueryList | null = null

const activeMenu = computed(() => {
  if (String(route.name ?? '').startsWith('admin-')) {
    return '/admin'
  }
  if (route.name === 'agent-chat') {
    return '/agents'
  }
  return route.path
})

const isChatRoute = computed(() => route.name === 'agent-chat')
const effectiveSidebarCollapsed = computed(() => sidebarCollapsed.value && isDesktop.value)
const sidebarWidth = computed(() => (effectiveSidebarCollapsed.value ? '72px' : '256px'))

function logout() {
  authStore.logout()
  router.push({ name: 'login' })
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('sairui:main-sidebar-collapsed', String(sidebarCollapsed.value))
}

function syncViewport() {
  isDesktop.value = mediaQuery?.matches ?? true
}

onMounted(() => {
  mediaQuery = window.matchMedia('(min-width: 901px)')
  syncViewport()
  mediaQuery.addEventListener('change', syncViewport)
})

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener('change', syncViewport)
})
</script>

<template>
  <el-container class="workbench-layout">
    <el-aside
      class="workbench-sidebar"
      :class="{ 'workbench-sidebar--collapsed': effectiveSidebarCollapsed }"
      :width="sidebarWidth"
    >
      <div class="brand">
        <div class="brand-mark">
          <img class="brand-logo" :src="sairuiLogo" alt="赛锐Agent" />
        </div>
        <div class="brand-copy">
          <strong>{{ appStore.systemName }}</strong>
        </div>
        <el-tooltip :content="effectiveSidebarCollapsed ? '展开导航' : '收起导航'">
          <el-button
            class="sidebar-toggle"
            :icon="effectiveSidebarCollapsed ? Expand : Fold"
            circle
            plain
            size="small"
            @click="toggleSidebar"
          />
        </el-tooltip>
      </div>

      <el-menu
        class="side-menu"
        :default-active="activeMenu"
        :collapse="effectiveSidebarCollapsed"
        router
        background-color="transparent"
      >
        <el-menu-item index="/">
          <el-icon><House /></el-icon>
          <span>首页</span>
        </el-menu-item>
        <el-menu-item index="/agents">
          <el-icon><Collection /></el-icon>
          <span>Agent 广场</span>
        </el-menu-item>
        <el-menu-item index="/runs">
          <el-icon><DataBoard /></el-icon>
          <span>任务中心</span>
        </el-menu-item>
        <el-menu-item index="/files">
          <el-icon><Files /></el-icon>
          <span>文件中心</span>
        </el-menu-item>
        <el-menu-item v-if="authStore.isAdmin" index="/admin">
          <el-icon><Management /></el-icon>
          <span>管理后台</span>
        </el-menu-item>
        <el-menu-item v-if="authStore.isAdmin" index="/admin/users">
          <el-icon><User /></el-icon>
          <span>用户管理</span>
        </el-menu-item>
        <el-menu-item v-if="authStore.isAdmin" index="/admin/agents">
          <el-icon><ChatDotRound /></el-icon>
          <span>Agent 管理</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container class="workbench-main">
      <el-header class="workbench-header" height="64px">
        <div class="header-title">赛锐Agent</div>
        <div class="header-user">
          <el-tag :type="authStore.isAdmin ? 'warning' : 'info'" effect="plain">
            {{ authStore.user?.role ?? 'user' }}
          </el-tag>
          <span class="user-name">{{ authStore.user?.display_name || authStore.user?.username }}</span>
          <el-button link :icon="SwitchButton" @click="logout">退出</el-button>
        </div>
      </el-header>

      <el-main class="workbench-content" :class="{ 'workbench-content--chat': isChatRoute }">
        <slot />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.workbench-layout {
  height: 100vh;
  min-height: 100vh;
  background: #eef3f8;
  color: #202124;
  overflow: hidden;
}

.workbench-sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  padding: 18px 12px;
  border-right: 1px solid #dfe5ee;
  background: #f7f9fc;
  transition: width 0.18s ease;
  overflow-x: hidden;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0 18px;
}

.workbench-sidebar--collapsed .brand {
  flex-direction: column;
  justify-content: center;
  gap: 8px;
  padding-inline: 0;
}

.brand-mark {
  display: flex;
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  overflow: hidden;
}

.brand-logo {
  display: block;
  width: 40px;
  height: 40px;
  object-fit: contain;
}

.brand-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.brand-copy strong {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench-sidebar--collapsed .brand-copy {
  display: none;
}

.sidebar-toggle {
  flex: 0 0 auto;
  width: 40px;
  height: 40px;
  margin-left: auto;
}

.workbench-sidebar--collapsed .sidebar-toggle {
  margin-left: 0;
}

.brand-copy span {
  color: #6f7785;
  font-size: 12px;
}

.side-menu {
  border-right: 0;
}

.side-menu:not(.el-menu--collapse) {
  width: 100%;
}

.side-menu :deep(.el-menu-item) {
  height: 42px;
  margin: 4px 0;
  border-radius: 20px;
  color: #3c4043;
}

.workbench-sidebar--collapsed .side-menu {
  display: grid;
  justify-items: center;
}

.workbench-sidebar--collapsed .side-menu.el-menu--collapse {
  width: 48px;
}

.workbench-sidebar--collapsed .side-menu :deep(.el-menu-item) {
  display: flex;
  width: 40px;
  height: 40px;
  justify-content: center;
  margin: 6px auto;
  padding: 0 !important;
  border-radius: 12px;
}

.workbench-sidebar--collapsed .side-menu :deep(.el-menu-item .el-icon) {
  margin: 0;
}

.side-menu :deep(.el-menu-item.is-active) {
  background: #dfe9fb;
  color: #174ea6;
}

.workbench-main {
  height: 100vh;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.workbench-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid #dfe5ee;
  background: rgb(255 255 255 / 72%);
  backdrop-filter: blur(10px);
}

.header-title {
  overflow: hidden;
  color: #5f6368;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-user {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.user-name {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench-content {
  height: calc(100vh - 64px);
  min-width: 0;
  min-height: 0;
  box-sizing: border-box;
  padding: 28px;
  overflow: auto;
}

.workbench-content--chat {
  display: grid;
  grid-template-rows: minmax(0, 1fr);
  height: calc(100dvh - 64px);
  box-sizing: border-box;
  padding: 12px;
  overflow: hidden;
}

@media (max-width: 900px) {
  .workbench-layout {
    display: block;
    height: auto;
    min-height: 100vh;
    overflow: auto;
  }

  .workbench-sidebar {
    position: static;
    width: 100% !important;
    height: auto;
    padding: 10px 12px;
  }

  .brand {
    padding-bottom: 8px;
  }

  .workbench-sidebar--collapsed .brand {
    flex-direction: row;
    justify-content: flex-start;
  }

  .workbench-sidebar--collapsed .brand-copy {
    display: grid;
  }

  .workbench-sidebar--collapsed .sidebar-toggle {
    margin-left: auto;
  }

  .side-menu {
    display: flex;
    overflow-x: auto;
  }

  .side-menu :deep(.el-menu-item) {
    flex: 0 0 auto;
  }

  .workbench-header {
    padding: 0 14px;
  }

  .header-title {
    display: none;
  }

  .workbench-content {
    height: auto;
    padding: 16px;
  }

  .workbench-content--chat {
    height: calc(100dvh - 132px);
    min-height: 0;
    padding: 12px;
    overflow: hidden;
  }
}
</style>
