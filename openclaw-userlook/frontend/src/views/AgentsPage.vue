<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { fetchAgents, type Agent } from '../api/agents'
import AgentCard from '../components/AgentCard.vue'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const agents = ref<Agent[]>([])

async function loadAgents() {
  loading.value = true
  try {
    agents.value = await fetchAgents()
  } catch {
    ElMessage.error('Agent 列表加载失败')
  } finally {
    loading.value = false
  }
}

function logout() {
  authStore.logout()
  router.push({ name: 'login' })
}

onMounted(loadAgents)
</script>

<template>
  <main class="agents-page">
    <section class="agents-shell">
      <div class="header-row">
        <div>
          <h1>Agent 工作台</h1>
          <p>选择已授权的 Agent。当前阶段仅展示和管理 Agent，不调用 OpenClaw。</p>
        </div>
        <div class="header-actions">
          <el-button @click="router.push({ name: 'dashboard' })">返回首页</el-button>
          <el-button v-if="authStore.isAdmin" @click="router.push({ name: 'admin-agents' })">
            Agent 管理
          </el-button>
          <el-button type="primary" :loading="loading" @click="loadAgents">刷新</el-button>
          <el-button @click="logout">退出</el-button>
        </div>
      </div>

      <el-skeleton v-if="loading" :rows="6" animated />
      <el-empty
        v-else-if="agents.length === 0"
        description="暂无可访问的 Agent，请联系管理员授权。"
      />
      <div v-else class="agent-grid">
        <AgentCard v-for="agent in agents" :key="agent.code" :agent="agent" />
      </div>
    </section>
  </main>
</template>

<style scoped>
.agents-page {
  min-height: 100vh;
  background: #f5f7fb;
  color: #1f2937;
}

.agents-shell {
  width: min(1180px, calc(100% - 32px));
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
}

p {
  margin: 10px 0 0;
  color: #667085;
}

.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}

@media (max-width: 720px) {
  .agents-shell {
    width: min(100% - 24px, 1180px);
    padding: 28px 0;
  }

  .header-row {
    flex-direction: column;
  }

  .header-actions {
    justify-content: flex-start;
  }
}
</style>
