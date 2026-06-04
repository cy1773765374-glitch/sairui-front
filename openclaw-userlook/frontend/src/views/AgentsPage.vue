<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchAgents, type Agent } from '../api/agents'
import {
  addFavoriteAgent,
  fetchFavoriteAgents,
  removeFavoriteAgent,
  type FavoriteAgent,
} from '../api/favorites'
import AgentCard from '../components/AgentCard.vue'
import AgentCategoryTabs from '../components/AgentCategoryTabs.vue'
import AgentDetailCard from '../components/AgentDetailCard.vue'
import { useAuthStore } from '../stores/auth'
import { AGENT_GROUPS, getAgentGroup, type AgentGroup } from '../utils/agentGroup'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const agents = ref<Agent[]>([])
const favorites = ref<FavoriteAgent[]>([])
const keyword = ref('')
const activeGroup = ref<AgentGroup>('全部')

const hasKeyword = computed(() => keyword.value.trim().length > 0)
const visibleGroups = computed(() =>
  AGENT_GROUPS.filter((group): group is Exclude<AgentGroup, '全部'> => group !== '全部'),
)
const favoriteCodes = computed(() => new Set(favorites.value.map((agent) => agent.agent_code)))
const showSingleGroup = computed(() => !hasKeyword.value && activeGroup.value !== '全部')

const searchedAgents = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return agents.value.filter((agent) => {
    if (!text) {
      return true
    }
    const values = authStore.isAdmin
      ? [agent.name, agent.code, agent.description, agent.openclaw_agent_id, agent.category]
      : [agent.name, agent.description, agent.category]
    return values.filter(Boolean).some((value) => String(value).toLowerCase().includes(text))
  })
})

const groupedAgents = computed(() => {
  const groups = Object.fromEntries(visibleGroups.value.map((group) => [group, [] as Agent[]])) as Record<
    Exclude<AgentGroup, '全部'>,
    Agent[]
  >
  for (const agent of searchedAgents.value) {
    groups[getAgentGroup(agent.name)].push(agent)
  }
  return groups
})

const filteredAgents = computed(() => {
  if (hasKeyword.value || activeGroup.value === '全部') {
    return searchedAgents.value
  }
  return searchedAgents.value.filter((agent) => getAgentGroup(agent.name) === activeGroup.value)
})

async function loadAgents() {
  loading.value = true
  try {
    const [agentResult, favoriteResult] = await Promise.all([
      fetchAgents(),
      fetchFavoriteAgents(),
    ])
    agents.value = agentResult
    favorites.value = favoriteResult
  } catch {
    ElMessage.error('Agent 列表加载失败')
  } finally {
    loading.value = false
  }
}

function openChat(agent: Agent) {
  router.push({ name: 'agent-chat', params: { agentCode: agent.code } })
}

async function toggleFavorite(agent: Agent) {
  try {
    if (favoriteCodes.value.has(agent.code)) {
      await removeFavoriteAgent(agent.code)
      favorites.value = favorites.value.filter((favorite) => favorite.agent_code !== agent.code)
      ElMessage.success('已取消收藏')
      return
    }
    const favorite = await addFavoriteAgent(agent.code)
    favorites.value = [...favorites.value, favorite]
    ElMessage.success('已加入常用')
  } catch {
    ElMessage.error('收藏状态更新失败')
  }
}

onMounted(loadAgents)
</script>

<template>
  <section class="agents-page page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">Agent 广场</p>
        <h1>Agent 广场</h1>
        <p>按名称首字母分组查找 Agent，收藏后可在首页直接进入对话。</p>
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
        <AgentCategoryTabs v-model="activeGroup" />
      </div>
    </el-card>

    <el-skeleton v-if="loading" :rows="6" animated />
    <el-empty
      v-else-if="filteredAgents.length === 0"
      description="暂无符合条件的 Agent，请调整搜索或分类"
    />

    <div v-else-if="showSingleGroup" class="agent-grid" :class="{ 'agent-grid--simple': !authStore.isAdmin }">
      <template v-for="agent in filteredAgents" :key="agent.code">
        <AgentDetailCard
          v-if="authStore.isAdmin"
          :agent="agent"
          :favorited="favoriteCodes.has(agent.code)"
          @open-chat="openChat"
          @toggle-favorite="toggleFavorite"
        />
        <AgentCard
          v-else
          :agent="agent"
          :favorited="favoriteCodes.has(agent.code)"
          @open-chat="openChat"
          @toggle-favorite="toggleFavorite"
        />
      </template>
    </div>

    <div v-else class="agent-groups">
      <section
        v-for="group in visibleGroups"
        v-show="groupedAgents[group].length > 0"
        :key="group"
        class="agent-group"
      >
        <header class="agent-group__header">
          <h2>{{ group }}</h2>
          <span>{{ groupedAgents[group].length }} 个 Agent</span>
        </header>
        <div class="agent-grid" :class="{ 'agent-grid--simple': !authStore.isAdmin }">
          <template v-for="agent in groupedAgents[group]" :key="agent.code">
            <AgentDetailCard
              v-if="authStore.isAdmin"
              :agent="agent"
              :favorited="favoriteCodes.has(agent.code)"
              @open-chat="openChat"
              @toggle-favorite="toggleFavorite"
            />
            <AgentCard
              v-else
              :agent="agent"
              :favorited="favoriteCodes.has(agent.code)"
              @open-chat="openChat"
              @toggle-favorite="toggleFavorite"
            />
          </template>
        </div>
      </section>
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
h2,
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

.filter-row {
  flex-wrap: wrap;
}

.filter-row .el-input {
  max-width: 360px;
}

.agent-groups {
  display: grid;
  gap: 22px;
}

.agent-group {
  display: grid;
  gap: 12px;
}

.agent-group__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 2px;
}

.agent-group__header h2 {
  font-size: 18px;
}

.agent-group__header span {
  color: #667085;
  font-size: 13px;
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

  .agent-grid--simple {
    grid-template-columns: 1fr;
  }
}
</style>
