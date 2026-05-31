<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { fetchHealth, type HealthResponse } from '../api/health'
import { useAppStore } from '../stores/app'
import { useAuthStore } from '../stores/auth'

const appStore = useAppStore()
const authStore = useAuthStore()
const router = useRouter()
const loading = ref(false)
const health = ref<HealthResponse | null>(null)
const errorMessage = ref('')

async function loadHealth() {
  loading.value = true
  errorMessage.value = ''

  try {
    health.value = await fetchHealth()
  } catch {
    health.value = null
    errorMessage.value = '后端健康检查失败'
    ElMessage.error(errorMessage.value)
  } finally {
    loading.value = false
  }
}

function logout() {
  authStore.logout()
  router.push({ name: 'login' })
}

onMounted(loadHealth)
</script>

<template>
  <main class="dashboard-page">
    <section class="dashboard-shell">
      <div class="header-row">
        <div>
          <h1>{{ appStore.systemName }}</h1>
          <p>当前版本：{{ appStore.phase }}</p>
        </div>
        <div class="header-actions">
          <el-button type="primary" @click="router.push({ name: 'agents' })">
            Agent 工作台
          </el-button>
          <el-button @click="router.push({ name: 'runs' })">
            任务中心
          </el-button>
          <el-button @click="router.push({ name: 'files' })">
            文件中心
          </el-button>
          <el-button v-if="authStore.isAdmin" @click="router.push({ name: 'admin-agents' })">
            Agent 管理
          </el-button>
          <el-button v-if="authStore.isAdmin" @click="router.push({ name: 'admin-users' })">
            用户审核
          </el-button>
          <el-button :loading="loading" @click="loadHealth">
            刷新状态
          </el-button>
          <el-button @click="logout">退出</el-button>
        </div>
      </div>

      <el-card class="status-card" shadow="never">
        <template #header>
          <div class="card-header">
            <span>当前用户</span>
            <el-tag v-if="authStore.user" :type="authStore.isAdmin ? 'warning' : 'success'">
              {{ authStore.user.role }}
            </el-tag>
          </div>
        </template>
        <el-descriptions v-if="authStore.user" :column="1" border>
          <el-descriptions-item label="用户名">
            {{ authStore.user.username }}
          </el-descriptions-item>
          <el-descriptions-item label="显示名称">
            {{ authStore.user.display_name }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag type="success">{{ authStore.user.status }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card class="status-card" shadow="never">
        <template #header>
          <span>后端健康检查结果</span>
        </template>

        <el-skeleton v-if="loading" :rows="3" animated />
        <el-result
          v-else-if="errorMessage"
          icon="error"
          title="连接失败"
          :sub-title="errorMessage"
        />
        <el-descriptions v-else-if="health" :column="1" border>
          <el-descriptions-item label="状态">
            <el-tag type="success">{{ health.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="服务">
            {{ health.service }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>
    </section>
  </main>
</template>

<style scoped>
.dashboard-page {
  min-height: 100vh;
  background: #f5f7fb;
  color: #1f2937;
}

.dashboard-shell {
  width: min(960px, calc(100% - 32px));
  margin: 0 auto;
  padding: 48px 0;
}

.header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
}

.header-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

h1 {
  margin: 0;
  font-size: 30px;
  line-height: 1.25;
  font-weight: 700;
}

p {
  margin: 10px 0 0;
  color: #667085;
}

.status-card {
  margin-top: 16px;
  border-radius: 8px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

@media (max-width: 640px) {
  .dashboard-shell {
    width: min(100% - 24px, 960px);
    padding: 28px 0;
  }

  .header-row {
    flex-direction: column;
  }

  .header-actions {
    justify-content: flex-start;
  }

  h1 {
    font-size: 24px;
  }
}
</style>
