<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ChatDotRound, Collection, DataBoard, Refresh, TrendCharts } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchAgents, type Agent } from '../api/agents'
import { fetchConversations, type Conversation } from '../api/conversations'
import { fetchHealth, type HealthResponse } from '../api/health'
import { fetchRuns, type TaskRun } from '../api/runs'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const loading = ref(false)
const health = ref<HealthResponse | null>(null)
const agents = ref<Agent[]>([])
const runs = ref<TaskRun[]>([])
const conversations = ref<Conversation[]>([])

const recentRuns = computed(() => runs.value.slice(0, 5))
const recentConversations = computed(() => conversations.value.slice(0, 5))
const highRiskCount = computed(() => agents.value.filter((agent) => agent.risk_level === 'high').length)
const runningCount = computed(() => runs.value.filter((run) => run.status === 'running' || run.status === 'pending').length)

function statusType(status: TaskRun['status']) {
  if (status === 'success') {
    return 'success'
  }
  if (status === 'failed' || status === 'cancelled') {
    return 'danger'
  }
  if (status === 'running') {
    return 'warning'
  }
  return 'info'
}

async function loadDashboard() {
  loading.value = true
  try {
    const [healthResult, agentResult, runResult, conversationResult] = await Promise.all([
      fetchHealth(),
      fetchAgents(),
      fetchRuns(),
      fetchConversations(),
    ])
    health.value = healthResult
    agents.value = agentResult
    runs.value = runResult
    conversations.value = conversationResult
  } catch {
    ElMessage.error('Dashboard 数据加载失败')
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
        <p class="eyebrow">Dashboard</p>
        <h1>OpenClaw 多 Agent 工作台</h1>
        <p>查看系统状态、当前账号、最近任务和会话。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadDashboard">刷新</el-button>
    </header>

    <el-row :gutter="16">
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card class="metric-card" shadow="never">
          <el-icon><TrendCharts /></el-icon>
          <span>系统状态</span>
          <strong>{{ health?.status || 'unknown' }}</strong>
          <small>{{ health?.service || 'FastAPI' }}</small>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card class="metric-card" shadow="never">
          <el-icon><Collection /></el-icon>
          <span>可用 Agent</span>
          <strong>{{ agents.length }}</strong>
          <small>{{ highRiskCount }} 个高风险</small>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card class="metric-card" shadow="never">
          <el-icon><DataBoard /></el-icon>
          <span>进行中任务</span>
          <strong>{{ runningCount }}</strong>
          <small>pending / running</small>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card class="metric-card" shadow="never">
          <el-icon><ChatDotRound /></el-icon>
          <span>最近会话</span>
          <strong>{{ conversations.length }}</strong>
          <small>{{ authStore.user?.display_name || authStore.user?.username }}</small>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="10">
        <el-card class="panel-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>当前用户</span>
              <el-tag :type="authStore.isAdmin ? 'warning' : 'success'" effect="plain">
                {{ authStore.user?.role }}
              </el-tag>
            </div>
          </template>
          <el-descriptions v-if="authStore.user" :column="1" border>
            <el-descriptions-item label="用户名">{{ authStore.user.username }}</el-descriptions-item>
            <el-descriptions-item label="显示名">{{ authStore.user.display_name }}</el-descriptions-item>
            <el-descriptions-item label="账号状态">
              <el-tag type="success" effect="plain">{{ authStore.user.status }}</el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
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
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" effect="plain">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="Agent" min-width="140">
              <template #default="{ row }">{{ row.agent_name || row.agent_code || row.agent_id }}</template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" min-width="170" />
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
        <el-table-column prop="updated_at" label="更新时间" min-width="180" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
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
  gap: 20px;
}

.page-heading,
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
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

.metric-card,
.panel-card {
  border-radius: 8px;
}

.metric-card {
  margin-bottom: 16px;
}

.metric-card :deep(.el-card__body) {
  display: grid;
  gap: 6px;
}

.metric-card .el-icon {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #eef3fe;
  color: #1a73e8;
  font-size: 18px;
}

.metric-card span,
.metric-card small {
  color: #6f7785;
}

.metric-card strong {
  font-size: 28px;
  line-height: 1.15;
}

@media (max-width: 720px) {
  .page-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
