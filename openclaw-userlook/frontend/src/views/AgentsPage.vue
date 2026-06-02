<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchAgents, type Agent } from '../api/agents'
import AgentCard from '../components/AgentCard.vue'
import AgentDetailCard from '../components/AgentDetailCard.vue'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const agents = ref<Agent[]>([])
const keyword = ref('')
const category = ref('all')

const categories = computed(() => {
  const values = new Set(agents.value.map((agent) => agent.category || '未分类'))
  return ['all', ...Array.from(values)]
})

const filteredAgents = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return agents.value.filter((agent) => {
    if (!authStore.isAdmin) {
      return !text || agent.name.toLowerCase().includes(text)
    }

    const agentCategory = agent.category || '未分类'
    const matchesCategory = category.value === 'all' || agentCategory === category.value
    const matchesKeyword =
      !text ||
      [agent.name, agent.code, agent.description, agent.openclaw_agent_id, agentCategory]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(text))
    return matchesCategory && matchesKeyword
  })
})

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

function openChat(agent: Agent) {
  router.push({ name: 'agent-chat', params: { agentCode: agent.code } })
}

onMounted(loadAgents)
</script>

<template>
  <section class="agents-page page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">Agents</p>
        <h1>Agent 广场</h1>
        <p v-if="authStore.isAdmin">选择已授权 Agent，按业务类别、关键词和能力快速定位。</p>
        <p v-else>选择已授权 Agent，点击名称即可进入对话。</p>
      </div>
      <div class="heading-actions">
        <el-button v-if="authStore.isAdmin" @click="router.push({ name: 'admin-agents' })">
          Agent 管理
        </el-button>
        <el-button type="primary" :icon="Refresh" :loading="loading" @click="loadAgents">刷新</el-button>
      </div>
    </header>

    <el-card class="filter-card" shadow="never">
      <div class="filter-row">
        <el-input
          v-model="keyword"
          :prefix-icon="Search"
          clearable
          :placeholder="authStore.isAdmin ? '搜索 Agent 名称、编码、说明' : '搜索 Agent 名称'"
        />
        <el-segmented v-if="authStore.isAdmin" v-model="category" :options="categories" />
      </div>
    </el-card>

    <el-skeleton v-if="loading" :rows="6" animated />
    <el-empty
      v-else-if="filteredAgents.length === 0"
      description="暂无符合条件的 Agent，请调整筛选条件或联系管理员授权。"
    />
    <div v-else class="agent-grid" :class="{ 'agent-grid--simple': !authStore.isAdmin }">
      <template v-for="agent in filteredAgents" :key="agent.code">
        <AgentDetailCard v-if="authStore.isAdmin" :agent="agent" @open-chat="openChat" />
        <AgentCard v-else :agent="agent" @open-chat="openChat" />
      </template>
    </div>
  </section>
</template>

<style scoped>
.page-stack {
  display: grid;
  gap: 20px;
}

.page-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
}

.heading-actions,
.filter-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #1a73e8;
  font-size: 13px;
  font-weight: 700;
}

h1,
p {
  margin: 0;
}

h1 {
  font-size: 28px;
  line-height: 1.25;
}

.page-heading p:last-child {
  margin-top: 8px;
  color: #6f7785;
}

.filter-card {
  border-radius: 8px;
}

.filter-row .el-input {
  max-width: 360px;
}

.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
}

.agent-grid--simple {
  grid-template-columns: repeat(auto-fit, minmax(220px, 320px));
}

@media (max-width: 760px) {
  .page-heading,
  .filter-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .heading-actions,
  .filter-row .el-input {
    width: 100%;
  }

  .filter-row :deep(.el-segmented) {
    max-width: 100%;
    overflow-x: auto;
  }

  .agent-grid--simple {
    grid-template-columns: 1fr;
  }
}
</style>
