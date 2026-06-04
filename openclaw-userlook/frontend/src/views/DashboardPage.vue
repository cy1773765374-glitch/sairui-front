<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ChatDotRound, Collection, DataBoard, Refresh, TrendCharts } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchAgents, type Agent } from '../api/agents'
import { fetchConversations, type Conversation } from '../api/conversations'
import {
  fetchFavoriteAgents,
  removeFavoriteAgent,
  reorderFavoriteAgents,
  type FavoriteAgent,
} from '../api/favorites'
import { fetchHealth, type HealthResponse } from '../api/health'
import { fetchRuns, type TaskRun } from '../api/runs'
import FavoriteAgentsPanel from '../components/FavoriteAgentsPanel.vue'
import { formatDateTimeShanghai } from '../utils/time'

const router = useRouter()

const loading = ref(false)
const health = ref<HealthResponse | null>(null)
const agents = ref<Agent[]>([])
const runs = ref<TaskRun[]>([])
const conversations = ref<Conversation[]>([])
const favorites = ref<FavoriteAgent[]>([])

const recentRuns = computed(() => runs.value.slice(0, 5))
const recentConversations = computed(() => conversations.value.slice(0, 5))
const highRiskCount = computed(() => agents.value.filter((agent) => agent.risk_level === 'high').length)
const runningCount = computed(() =>
  runs.value.filter((run) => run.status === 'running' || run.status === 'pending' || run.status === 'queued').length,
)

function statusType(status: TaskRun['status']) {
  if (status === 'success') {
    return 'success'
  }
  if (status === 'failed' || status === 'cancelled' || status === 'timeout' || status === 'stale') {
    return 'danger'
  }
  if (status === 'running' || status === 'queued' || status === 'pending') {
    return 'warning'
  }
  return 'info'
}

function openAgentChat(agentCode: string) {
  router.push({ name: 'agent-chat', params: { agentCode } })
}

async function removeFavorite(agentCode: string) {
  try {
    await removeFavoriteAgent(agentCode)
    favorites.value = favorites.value.filter((agent) => agent.agent_code !== agentCode)
    ElMessage.success('已取消收藏')
  } catch {
    ElMessage.error('取消收藏失败')
  }
}

async function reorderFavorites(agentCodes: string[]) {
  const previous = favorites.value
  favorites.value = agentCodes
    .map((agentCode) => previous.find((agent) => agent.agent_code === agentCode))
    .filter((agent): agent is FavoriteAgent => Boolean(agent))
  try {
    favorites.value = await reorderFavoriteAgents(agentCodes)
  } catch {
    favorites.value = previous
    ElMessage.error('常用 Agent 排序保存失败')
  }
}

async function loadDashboard() {
  loading.value = true
  try {
    const [healthResult, agentResult, runResult, conversationResult, favoriteResult] = await Promise.all([
      fetchHealth(),
      fetchAgents(),
      fetchRuns(),
      fetchConversations(),
      fetchFavoriteAgents(),
    ])
    health.value = healthResult
    agents.value = agentResult
    runs.value = runResult
    conversations.value = conversationResult
    favorites.value = favoriteResult
  } catch {
    ElMessage.error('首页数据加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadDashboard)
</script>

<template>
  <section class="dashboard-page page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">首页</p>
        <h1>赛锐Agent</h1>
        <p>查看系统状态、常用 Agent、最近任务和最近会话。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadDashboard">刷新</el-button>
    </header>

    <section class="metric-grid">
      <el-card class="metric-card" shadow="never">
        <el-icon><TrendCharts /></el-icon>
        <span>系统状态</span>
        <strong>{{ health?.status || 'unknown' }}</strong>
        <small>{{ health?.service || 'FastAPI' }}</small>
      </el-card>
      <el-card class="metric-card" shadow="never">
        <el-icon><Collection /></el-icon>
        <span>可用 Agent</span>
        <strong>{{ agents.length }}</strong>
        <small>{{ highRiskCount }} 个高风险</small>
      </el-card>
      <el-card class="metric-card" shadow="never">
        <el-icon><DataBoard /></el-icon>
        <span>进行中任务</span>
        <strong>{{ runningCount }}</strong>
        <small>pending / queued / running</small>
      </el-card>
      <el-card class="metric-card" shadow="never">
        <el-icon><ChatDotRound /></el-icon>
        <span>最近会话</span>
        <strong>{{ conversations.length }}</strong>
        <small>按更新时间排序</small>
      </el-card>
    </section>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="10">
        <FavoriteAgentsPanel
          :favorites="favorites"
          :loading="loading"
          @open-chat="openAgentChat"
          @remove-favorite="removeFavorite"
          @reorder="reorderFavorites"
        />
      </el-col>

      <el-col :xs="24" :lg="14">
        <el-card class="panel-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>最近任务</span>
              <el-button link type="primary" @click="router.push({ name: 'runs' })">查看全部</el-button>
            </div>
          </template>
          <el-table v-loading="loading" :data="recentRuns" size="small">
            <el-table-column label="状态" width="96">
              <template #default="{ row }: { row: TaskRun }">
                <el-tag :type="statusType(row.status)" effect="plain">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="Agent" min-width="140">
              <template #default="{ row }: { row: TaskRun }">{{ row.agent_name || row.agent_code || row.agent_id }}</template>
            </el-table-column>
            <el-table-column label="创建时间" min-width="170">
              <template #default="{ row }: { row: TaskRun }">{{ formatDateTimeShanghai(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="panel-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>最近会话</span>
          <el-button link type="primary" @click="router.push({ name: 'agents' })">进入 Agent 广场</el-button>
        </div>
      </template>
      <el-table v-loading="loading" :data="recentConversations" size="small">
        <el-table-column prop="title" label="会话" min-width="220" />
        <el-table-column prop="agent_name" label="Agent" min-width="160" />
        <el-table-column label="更新时间" min-width="180">
          <template #default="{ row }: { row: Conversation }">{{ formatDateTimeShanghai(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }: { row: Conversation }">
            <el-button link type="primary" @click="router.push({ name: 'agent-chat', params: { agentCode: row.agent_code } })">
              打开
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>

<style scoped>
.page-stack {
  display: grid;
  gap: 16px;
}

.page-heading,
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.eyebrow {
  margin: 0 0 6px;
  color: #1a73e8;
  font-size: 13px;
  font-weight: 700;
}

h1,
p {
  margin: 0;
}

h1 {
  font-size: 26px;
  line-height: 1.25;
}

.page-heading p:last-child {
  margin-top: 6px;
  color: #6f7785;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric-card,
.panel-card {
  border-radius: 8px;
}

.metric-card :deep(.el-card__body) {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 2px 10px;
  align-items: center;
  padding: 14px 16px;
}

.metric-card .el-icon {
  grid-row: span 3;
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 8px;
  background: #eef3fe;
  color: #1a73e8;
  font-size: 18px;
}

.metric-card span,
.metric-card small {
  color: #6f7785;
}

.metric-card span {
  font-size: 13px;
}

.metric-card strong {
  font-size: 22px;
  line-height: 1.1;
}

@media (max-width: 1100px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .page-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
