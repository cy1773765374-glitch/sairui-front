<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ChatDotRound,
  Collection,
  DataBoard,
  Files,
  House,
  Management,
  SwitchButton,
  User,
} from '@element-plus/icons-vue'

import { useAppStore } from '../stores/app'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()

const activeMenu = computed(() => {
  if (String(route.name ?? '').startsWith('admin-')) {
    return '/admin'
  }
  if (route.name === 'agent-chat') {
    return '/agents'
  }
  return route.path
})

function logout() {
  authStore.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <el-container class="workbench-layout">
    <el-aside class="workbench-sidebar" width="256px">
      <div class="brand">
        <div class="brand-mark">O</div>
        <div class="brand-copy">
          <strong>{{ appStore.systemName }}</strong>
        </div>
      </div>

      <el-menu
        class="side-menu"
        :default-active="activeMenu"
        router
        background-color="transparent"
      >
        <el-menu-item index="/">
          <el-icon><House /></el-icon>
          <span>Dashboard</span>
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
        <div class="header-title">企业内部 OpenClaw 多 Agent 工作台</div>
        <div class="header-user">
          <el-tag :type="authStore.isAdmin ? 'warning' : 'info'" effect="plain">
            {{ authStore.user?.role ?? 'user' }}
          </el-tag>
          <span class="user-name">{{ authStore.user?.display_name || authStore.user?.username }}</span>
          <el-button link :icon="SwitchButton" @click="logout">退出</el-button>
        </div>
      </el-header>

      <el-main class="workbench-content">
        <slot />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.workbench-layout {
  min-height: 100vh;
  background: #eef3f8;
  color: #202124;
}

.workbench-sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  padding: 18px 12px;
  border-right: 1px solid #dfe5ee;
  background: #f7f9fc;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px 18px;
}

.brand-mark {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border-radius: 50%;
  background: linear-gradient(135deg, #3f7ee8, #18a058);
  color: #ffffff;
  font-weight: 700;
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

.brand-copy span {
  color: #6f7785;
  font-size: 12px;
}

.side-menu {
  border-right: 0;
}

.side-menu :deep(.el-menu-item) {
  height: 42px;
  margin: 4px 0;
  border-radius: 20px;
  color: #3c4043;
}

.side-menu :deep(.el-menu-item.is-active) {
  background: #dfe9fb;
  color: #174ea6;
}

.workbench-main {
  min-width: 0;
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
  min-width: 0;
  padding: 28px;
}

@media (max-width: 900px) {
  .workbench-layout {
    display: block;
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
    padding: 16px;
  }
}
</style>
