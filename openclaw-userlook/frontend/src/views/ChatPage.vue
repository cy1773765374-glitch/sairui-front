<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatDotRound, Document, Files, InfoFilled, Picture } from '@element-plus/icons-vue'
import { ElMessage, ElNotification } from 'element-plus'

import { fetchAgent, fetchAgents, type Agent, type AgentRiskLevel } from '../api/agents'
import {
  buildConversationWebSocketUrl,
  createConversation,
  fetchConversation,
  fetchConversations,
  type Conversation,
  type LocalMessage,
} from '../api/conversations'
import { downloadFile, formatFileSize, type UserFile } from '../api/files'
import type { TaskRunStatus } from '../api/runs'
import ChatWindow from '../components/ChatWindow.vue'

type ServerWsMessage =
  | { type: 'assistant_delta'; content: string }
  | { type: 'assistant_done'; message_id: number; run_id?: number; output_files?: UserFile[] }
  | {
      type: 'run_status'
      run_id?: number
      status: TaskRunStatus | 'done' | 'idle'
      message?: string
      output_files?: UserFile[]
    }
  | { type: 'error'; message: string }

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const connected = ref(false)
const sending = ref(false)
const detailDrawerVisible = ref(false)
const agents = ref<Agent[]>([])
const conversations = ref<Conversation[]>([])
const agent = ref<Agent | null>(null)
const conversation = ref<Conversation | null>(null)
const messages = ref<LocalMessage[]>([])
const activeAssistantMessageId = ref<string | null>(null)
const errorMessage = ref('')
const attachedFiles = ref<UserFile[]>([])
const outputFiles = ref<UserFile[]>([])
const currentRunId = ref<number | null>(null)
const currentRunStatus = ref<TaskRunStatus | ''>('')
const currentRunStatusMessage = ref('')

let socket: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectAttempts = 0
let unmounted = false
let suppressRouteWatch = false

const title = computed(() => conversation.value?.title ?? agent.value?.name ?? 'Agent 对话')
const subtitle = computed(() => {
  if (!conversation.value) {
    return '正在准备会话'
  }
  return `${conversation.value.agent_name} · ${conversation.value.session_key}`
})

const conversationsByAgent = computed(() => {
  if (!agent.value) {
    return conversations.value
  }
  return conversations.value.filter((item) => item.agent_id === agent.value?.id)
})

function riskTagType(riskLevel?: AgentRiskLevel) {
  if (riskLevel === 'high') {
    return 'danger'
  }
  if (riskLevel === 'medium') {
    return 'warning'
  }
  return 'success'
}

function normalizeMessages(serverMessages: Awaited<ReturnType<typeof fetchConversation>>['messages']) {
  messages.value = serverMessages.map((message) => ({ ...message, streaming: false }))
}

function parseConversationId(value: unknown) {
  const rawValue = Array.isArray(value) ? value[0] : value
  const numericValue = Number(rawValue)
  return Number.isInteger(numericValue) && numericValue > 0 ? numericValue : undefined
}

async function refreshSidebarData() {
  const [agentResult, conversationResult] = await Promise.all([fetchAgents(), fetchConversations()])
  agents.value = agentResult
  conversations.value = conversationResult
}

async function loadHistory(conversationId: number) {
  const detail = await fetchConversation(conversationId)
  conversation.value = detail
  normalizeMessages(detail.messages)
}

function clearReconnectTimer() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

function scheduleReconnect() {
  if (!conversation.value || unmounted) {
    return
  }
  if (reconnectAttempts >= 3) {
    ElNotification.error({
      title: 'WebSocket 重连失败',
      message: '连接已断开，请刷新页面或稍后重试。',
    })
    return
  }

  reconnectAttempts += 1
  ElNotification.warning({
    title: 'WebSocket 已断开',
    message: `正在尝试第 ${reconnectAttempts} 次重连。`,
  })
  const conversationId = conversation.value.id
  reconnectTimer = setTimeout(() => connectWebSocket(conversationId, true), 1500)
}

function connectWebSocket(conversationId: number, isReconnect = false) {
  clearReconnectTimer()
  if (!isReconnect) {
    reconnectAttempts = 0
  }
  if (socket) {
    socket.onclose = null
    socket.onerror = null
    socket.close()
  }

  socket = new WebSocket(buildConversationWebSocketUrl(conversationId))

  socket.onopen = () => {
    connected.value = true
    errorMessage.value = ''
    if (isReconnect) {
      ElNotification.success({
        title: 'WebSocket 已重连',
        message: '对话通道已恢复。',
      })
    }
    reconnectAttempts = 0
  }

  socket.onclose = () => {
    connected.value = false
    sending.value = false
    scheduleReconnect()
  }

  socket.onerror = () => {
    connected.value = false
    sending.value = false
    ElMessage.error('WebSocket 连接异常')
  }

  socket.onmessage = async (event) => {
    let payload: ServerWsMessage
    try {
      payload = JSON.parse(event.data) as ServerWsMessage
    } catch {
      ElMessage.error('WebSocket 消息解析失败')
      return
    }

    if (payload.type === 'assistant_delta') {
      errorMessage.value = ''
      if (!activeAssistantMessageId.value) {
        activeAssistantMessageId.value = `assistant-${Date.now()}`
        messages.value.push({
          id: activeAssistantMessageId.value,
          role: 'assistant',
          content: '',
          created_at: new Date().toISOString(),
          streaming: true,
        })
      }

      const target = messages.value.find((message) => message.id === activeAssistantMessageId.value)
      if (target) {
        target.content += payload.content
      }
      return
    }

    if (payload.type === 'run_status') {
      currentRunId.value = payload.run_id ?? currentRunId.value
      currentRunStatus.value =
        payload.status === 'done' ? 'success' : payload.status === 'idle' ? '' : payload.status
      currentRunStatusMessage.value = payload.message ?? ''
      if (payload.output_files) {
        outputFiles.value = payload.output_files
      }
      sending.value = !['success', 'failed', 'cancelled', 'done', 'idle'].includes(payload.status)
      if (['failed', 'cancelled', 'idle'].includes(payload.status)) {
        const target = messages.value.find((message) => message.id === activeAssistantMessageId.value)
        if (target) {
          target.streaming = false
        }
        activeAssistantMessageId.value = null
      }
      return
    }

    if (payload.type === 'assistant_done') {
      currentRunId.value = payload.run_id ?? currentRunId.value
      if (payload.output_files) {
        outputFiles.value = payload.output_files
      }
      const target = messages.value.find((message) => message.id === activeAssistantMessageId.value)
      if (target) {
        target.id = payload.message_id
        target.streaming = false
      }
      activeAssistantMessageId.value = null
      sending.value = false
      if (conversation.value) {
        await loadHistory(conversation.value.id)
        conversations.value = await fetchConversations()
      }
      return
    }

    errorMessage.value = payload.message
    ElMessage.error(payload.message)
    const target = messages.value.find((message) => message.id === activeAssistantMessageId.value)
    if (target) {
      target.streaming = false
    }
    activeAssistantMessageId.value = null
    sending.value = false
  }
}

async function ensureConversation(currentAgent: Agent, preferredConversationId?: number) {
  if (preferredConversationId) {
    await loadHistory(preferredConversationId)
    return
  }

  const existing = conversations.value.find((item) => item.agent_id === currentAgent.id)
  if (existing) {
    await loadHistory(existing.id)
    return
  }

  const created = await createConversation({
    agent_id: currentAgent.id,
    title: `${currentAgent.name} 对话`,
  })
  conversations.value = [created, ...conversations.value]
  await loadHistory(created.id)
}

async function initializeAgent(agentCode: string, preferredConversationId?: number) {
  loading.value = true
  errorMessage.value = ''
  attachedFiles.value = []
  outputFiles.value = []
  currentRunId.value = null
  currentRunStatus.value = ''
  currentRunStatusMessage.value = ''

  try {
    if (agents.value.length === 0 || conversations.value.length === 0) {
      await refreshSidebarData()
    }
    const currentAgent = agents.value.find((item) => item.code === agentCode) ?? (await fetchAgent(agentCode))
    agent.value = currentAgent
    await ensureConversation(currentAgent, preferredConversationId)
    if (conversation.value) {
      connectWebSocket(conversation.value.id)
    }
  } catch (error) {
    ElMessage.error('对话初始化失败')
    router.push({ name: 'agents' })
  } finally {
    loading.value = false
  }
}

async function selectAgent(nextAgent: Agent) {
  if (String(route.params.agentCode) === nextAgent.code) {
    await initializeAgent(nextAgent.code)
    return
  }
  router.push({ name: 'agent-chat', params: { agentCode: nextAgent.code }, query: {} })
}

async function selectConversation(nextConversation: Conversation) {
  suppressRouteWatch = true
  try {
    if (String(route.params.agentCode) !== nextConversation.agent_code) {
      await router.push({
        name: 'agent-chat',
        params: { agentCode: nextConversation.agent_code },
        query: { conversationId: String(nextConversation.id) },
      })
    } else {
      await router.push({
        name: 'agent-chat',
        params: { agentCode: nextConversation.agent_code },
        query: { conversationId: String(nextConversation.id) },
      })
    }
    await initializeAgent(nextConversation.agent_code, nextConversation.id)
  } finally {
    suppressRouteWatch = false
  }
}

async function sendMessage(content: string, fileIds: number[]) {
  if (!socket || socket.readyState !== WebSocket.OPEN || !conversation.value) {
    ElMessage.error('WebSocket 未连接')
    return
  }

  sending.value = true
  errorMessage.value = ''
  outputFiles.value = []
  currentRunStatusMessage.value = ''
  messages.value.push({
    id: `user-${Date.now()}`,
    conversation_id: conversation.value.id,
    role: 'user',
    content,
    created_at: new Date().toISOString(),
    raw_payload: { file_ids: fileIds },
    streaming: false,
  })

  try {
    socket.send(
      JSON.stringify({
        type: 'user_message',
        content,
        file_ids: fileIds,
      }),
    )
    attachedFiles.value = []
  } catch {
    sending.value = false
    ElMessage.error('消息发送失败')
  }
}

function stopCurrentRun() {
  if (!socket || socket.readyState !== WebSocket.OPEN || !currentRunId.value) {
    return
  }
  socket.send(
    JSON.stringify({
      type: 'cancel_run',
      run_id: currentRunId.value,
    }),
  )
  sending.value = false
  currentRunStatus.value = 'cancelled'
  currentRunStatusMessage.value = '正在停止当前回复'
  const target = messages.value.find((message) => message.id === activeAssistantMessageId.value)
  if (target) {
    target.streaming = false
  }
}

function addUploadedFile(file: UserFile) {
  if (!attachedFiles.value.some((item) => item.id === file.id)) {
    attachedFiles.value.push(file)
  }
}

function removeAttachedFile(fileId: number) {
  attachedFiles.value = attachedFiles.value.filter((file) => file.id !== fileId)
}

watch(
  () => [route.params.agentCode, route.query.conversationId],
  ([agentCode, conversationId]) => {
    if (!suppressRouteWatch && agentCode) {
      initializeAgent(String(agentCode), parseConversationId(conversationId))
    }
  },
)

onMounted(async () => {
  await refreshSidebarData()
  const agentCode = String(route.params.agentCode || agents.value[0]?.code || '')
  if (!agentCode) {
    ElMessage.error('暂无可用 Agent')
    router.push({ name: 'agents' })
    return
  }
  await initializeAgent(agentCode, parseConversationId(route.query.conversationId))
})

onBeforeUnmount(() => {
  unmounted = true
  clearReconnectTimer()
  if (socket) {
    socket.onclose = null
    socket.onerror = null
    socket.close()
  }
})
</script>

<template>
  <section class="chat-page">
    <aside class="chat-panel left-panel">
      <el-card shadow="never">
        <template #header>
          <div class="panel-header">
            <span>可用 Agent</span>
            <el-tag effect="plain">{{ agents.length }}</el-tag>
          </div>
        </template>
        <div class="agent-list">
          <button
            v-for="item in agents"
            :key="item.code"
            class="list-item"
            :class="{ active: item.code === agent?.code }"
            type="button"
            @click="selectAgent(item)"
          >
            <span>{{ item.name }}</span>
            <el-tag size="small" :type="riskTagType(item.risk_level)" effect="plain">
              {{ item.risk_level }}
            </el-tag>
          </button>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="panel-header">
            <span>历史会话</span>
            <el-tag effect="plain">{{ conversationsByAgent.length }}</el-tag>
          </div>
        </template>
        <div class="conversation-list">
          <button
            v-for="item in conversationsByAgent"
            :key="item.id"
            class="list-item conversation-item"
            :class="{ active: item.id === conversation?.id }"
            type="button"
            @click="selectConversation(item)"
          >
            <span>{{ item.title }}</span>
            <small>{{ item.updated_at }}</small>
          </button>
          <el-empty v-if="conversationsByAgent.length === 0" description="暂无历史会话" />
        </div>
      </el-card>
    </aside>

    <main class="chat-main">
      <el-button class="mobile-detail-button" :icon="InfoFilled" @click="detailDrawerVisible = true">
        Agent 详情
      </el-button>
      <ChatWindow
        :title="title"
        :subtitle="subtitle"
        :messages="messages"
        :connected="connected"
        :sending="sending"
        :loading="loading"
        :error-message="errorMessage"
        :attached-files="attachedFiles"
        :run-id="currentRunId"
        :run-status="currentRunStatus"
        :run-status-message="currentRunStatusMessage"
        :output-files="outputFiles"
        @send="sendMessage"
        @stop="stopCurrentRun"
        @file-uploaded="addUploadedFile"
        @remove-file="removeAttachedFile"
      />
    </main>

    <aside class="chat-panel details-panel">
      <el-card shadow="never">
        <template #header>
          <div class="panel-header">
            <span>当前 Agent</span>
            <el-tag v-if="agent" :type="riskTagType(agent.risk_level)" effect="plain">
              {{ agent.risk_level }}
            </el-tag>
          </div>
        </template>
        <div v-if="agent" class="agent-detail">
          <h2>{{ agent.name }}</h2>
          <p>{{ agent.description || '暂无说明' }}</p>
          <div class="capability-tags">
            <el-tag plain><el-icon><ChatDotRound /></el-icon>{{ agent.category || '未分类' }}</el-tag>
            <el-tag :type="agent.support_files ? 'success' : 'info'" plain>
              <el-icon><Files /></el-icon>文件{{ agent.support_files ? '支持' : '不支持' }}
            </el-tag>
            <el-tag :type="agent.support_images ? 'success' : 'info'" plain>
              <el-icon><Picture /></el-icon>图片{{ agent.support_images ? '支持' : '不支持' }}
            </el-tag>
          </div>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>当前 task_run</template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="Run ID">{{ currentRunId || '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag v-if="currentRunStatus" effect="plain">{{ currentRunStatus }}</el-tag>
            <span v-else>idle</span>
          </el-descriptions-item>
          <el-descriptions-item label="说明">{{ currentRunStatusMessage || '-' }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="panel-header">
            <span>输出文件</span>
            <el-tag effect="plain">{{ outputFiles.length }}</el-tag>
          </div>
        </template>
        <div class="output-list">
          <el-button
            v-for="file in outputFiles"
            :key="file.id"
            link
            type="primary"
            :icon="Document"
            @click="downloadFile(file)"
          >
            {{ file.original_name }} · {{ formatFileSize(file.file_size) }}
          </el-button>
          <el-empty v-if="outputFiles.length === 0" description="暂无输出文件" />
        </div>
      </el-card>
    </aside>

    <el-drawer v-model="detailDrawerVisible" title="Agent 详情" size="360px">
      <div v-if="agent" class="agent-detail drawer-detail">
        <h2>{{ agent.name }}</h2>
        <p>{{ agent.description || '暂无说明' }}</p>
        <div class="capability-tags">
          <el-tag :type="riskTagType(agent.risk_level)" effect="plain">{{ agent.risk_level }}</el-tag>
          <el-tag plain>{{ agent.category || '未分类' }}</el-tag>
          <el-tag :type="agent.support_files ? 'success' : 'info'" plain>
            文件{{ agent.support_files ? '支持' : '不支持' }}
          </el-tag>
          <el-tag :type="agent.support_images ? 'success' : 'info'" plain>
            图片{{ agent.support_images ? '支持' : '不支持' }}
          </el-tag>
        </div>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.chat-page {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr) 300px;
  gap: 16px;
  align-items: stretch;
  height: calc(100vh - 120px);
  min-height: 0;
}

.chat-panel {
  display: grid;
  align-content: start;
  gap: 16px;
  min-height: 0;
  overflow-y: auto;
}

.chat-panel .el-card {
  border-radius: 8px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.agent-list,
.conversation-list,
.output-list {
  display: grid;
  gap: 8px;
}

.list-item {
  display: flex;
  width: 100%;
  min-height: 42px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border: 0;
  border-radius: 20px;
  background: transparent;
  color: #3c4043;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.list-item:hover,
.list-item.active {
  background: #dfe9fb;
}

.list-item span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-item {
  display: grid;
  justify-items: start;
  border-radius: 12px;
}

.conversation-item small {
  color: #6f7785;
  font-size: 12px;
}

.chat-main {
  display: grid;
  min-width: 0;
  min-height: 0;
}

.mobile-detail-button {
  display: none;
  margin-bottom: 12px;
}

.agent-detail {
  display: grid;
  gap: 12px;
}

.agent-detail h2,
.agent-detail p {
  margin: 0;
}

.agent-detail h2 {
  font-size: 18px;
}

.agent-detail p {
  color: #6f7785;
  line-height: 1.6;
}

.capability-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.output-list .el-button {
  justify-content: flex-start;
  min-width: 0;
  white-space: normal;
}

@media (max-width: 1180px) {
  .chat-page {
    grid-template-columns: 260px minmax(0, 1fr);
  }

  .details-panel {
    display: none;
  }

  .mobile-detail-button {
    display: inline-flex;
  }
}

@media (max-width: 820px) {
  .chat-page {
    grid-template-columns: 1fr;
    height: auto;
  }
}
</style>
