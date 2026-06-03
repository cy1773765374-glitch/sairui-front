<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatDotRound, Delete, Document, Files, InfoFilled, Picture, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'

import { fetchAgent, fetchAgents, type Agent, type AgentRiskLevel } from '../api/agents'
import {
  buildConversationWebSocketUrl,
  createConversation,
  deleteConversation,
  fetchConversation,
  fetchConversations,
  type Conversation,
  type LocalMessage,
} from '../api/conversations'
import { downloadFile, formatFileSize, type UserFile } from '../api/files'
import { cancelRun, fetchRun, isActiveRunStatus, type TaskRun, type TaskRunStatus } from '../api/runs'
import ChatWindow from '../components/ChatWindow.vue'

type ServerWsMessage =
  | { type: 'assistant_delta'; content: string }
  | { type: 'assistant_done'; message_id: number; run_id?: number; output_files?: UserFile[] }
  | {
      type: 'run_status'
      run_id?: number
      conversation_id?: number
      queue_status?: 'queued' | 'immediate'
      status: TaskRunStatus | 'done' | 'idle'
      message?: string
      output_files?: UserFile[]
    }
  | { type: 'active_run'; message?: string; active_run: TaskRun | null }
  | { type: 'error'; message: string }

interface ConversationRuntimeState {
  sending: boolean
  activeAssistantMessageId: string | null
  outputFiles: UserFile[]
  currentRunId: number | null
  currentRunStatus: TaskRunStatus | ''
  currentRunStatusMessage: string
}

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const connected = ref(false)
const detailDrawerVisible = ref(false)
const agents = ref<Agent[]>([])
const conversations = ref<Conversation[]>([])
const agent = ref<Agent | null>(null)
const conversation = ref<Conversation | null>(null)
const messages = ref<LocalMessage[]>([])
const errorMessage = ref('')
const attachedFiles = ref<UserFile[]>([])
const deletingConversationId = ref<number | null>(null)
const runtimeByConversation = ref<Record<number, ConversationRuntimeState>>({})
const fallbackRuntime = ref<ConversationRuntimeState>(createRuntimeState())

let socket: WebSocket | null = null
let socketConversationId: number | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectAttempts = 0
let unmounted = false
let suppressRouteWatch = false
let activeInitializeRequestId = 0

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

const activeRuntime = computed(() => {
  if (!conversation.value) {
    return fallbackRuntime.value
  }
  return getRuntimeForConversation(conversation.value.id)
})

const sending = computed({
  get: () => activeRuntime.value.sending,
  set: (value: boolean) => {
    activeRuntime.value.sending = value
  },
})

const activeAssistantMessageId = computed({
  get: () => activeRuntime.value.activeAssistantMessageId,
  set: (value: string | null) => {
    activeRuntime.value.activeAssistantMessageId = value
  },
})

const outputFiles = computed({
  get: () => activeRuntime.value.outputFiles,
  set: (value: UserFile[]) => {
    activeRuntime.value.outputFiles = value
  },
})

const currentRunId = computed({
  get: () => activeRuntime.value.currentRunId,
  set: (value: number | null) => {
    activeRuntime.value.currentRunId = value
  },
})

const currentRunStatus = computed({
  get: () => activeRuntime.value.currentRunStatus,
  set: (value: TaskRunStatus | '') => {
    activeRuntime.value.currentRunStatus = value
  },
})

const currentRunStatusMessage = computed({
  get: () => activeRuntime.value.currentRunStatusMessage,
  set: (value: string) => {
    activeRuntime.value.currentRunStatusMessage = value
  },
})

function createRuntimeState(): ConversationRuntimeState {
  return {
    sending: false,
    activeAssistantMessageId: null,
    outputFiles: [],
    currentRunId: null,
    currentRunStatus: '',
    currentRunStatusMessage: '',
  }
}

function getRuntimeForConversation(conversationId: number) {
  if (!runtimeByConversation.value[conversationId]) {
    runtimeByConversation.value[conversationId] = createRuntimeState()
  }
  return runtimeByConversation.value[conversationId]
}

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

function applyRunState(run: TaskRun | null) {
  const runtime =
    run?.conversation_id ? getRuntimeForConversation(run.conversation_id) : activeRuntime.value
  runtime.currentRunId = run?.id ?? null
  runtime.currentRunStatus = run?.status ?? ''
  runtime.currentRunStatusMessage = run?.error_message ?? ''
  runtime.outputFiles = run?.output_files ?? []
  runtime.sending = isActiveRunStatus(run?.status)
  if (!runtime.sending) {
    runtime.activeAssistantMessageId = null
  }
}

function resetConversationRuntimeState(conversationId?: number) {
  const nextState = createRuntimeState()
  if (conversationId) {
    runtimeByConversation.value[conversationId] = nextState
    return
  }
  fallbackRuntime.value = nextState
}

function parseConversationId(value: unknown) {
  const rawValue = Array.isArray(value) ? value[0] : value
  const numericValue = Number(rawValue)
  return Number.isInteger(numericValue) && numericValue > 0 ? numericValue : undefined
}

async function refreshSidebarData(requestId = activeInitializeRequestId) {
  const [agentResult, conversationResult] = await Promise.all([fetchAgents(), fetchConversations()])
  if (!isActiveInitializeRequest(requestId)) {
    return
  }
  agents.value = agentResult
  conversations.value = conversationResult
}

function isActiveInitializeRequest(requestId: number) {
  return !unmounted && requestId === activeInitializeRequestId
}

async function loadHistory(
  conversationId: number,
  requestId = activeInitializeRequestId,
  expectedAgentId?: number,
) {
  const detail = await fetchConversation(conversationId)
  if (!isActiveInitializeRequest(requestId)) {
    return null
  }
  if (expectedAgentId !== undefined && detail.agent_id !== expectedAgentId) {
    return null
  }
  conversation.value = detail
  normalizeMessages(detail.messages)
  if (detail.active_run) {
    applyRunState(detail.active_run)
  } else {
    resetConversationRuntimeState(detail.id)
  }
  return detail
}

function clearReconnectTimer() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

function isCurrentSocket(currentSocket: WebSocket, conversationId: number) {
  return (
    !unmounted &&
    socket === currentSocket &&
    socketConversationId === conversationId &&
    conversation.value?.id === conversationId
  )
}

function scheduleReconnect(conversationId: number) {
  if (conversation.value?.id !== conversationId || unmounted) {
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
  reconnectTimer = setTimeout(() => {
    if (conversation.value?.id === conversationId && socketConversationId === conversationId) {
      connectWebSocket(conversationId, true)
    }
  }, 1500)
}

async function reconcileCurrentRun(conversationId: number) {
  if (!currentRunId.value) {
    sending.value = false
    activeAssistantMessageId.value = null
    return
  }
  try {
    const run = await fetchRun(currentRunId.value)
    if (conversation.value?.id !== conversationId) {
      return
    }
    applyRunState(run)
    if (isActiveRunStatus(run.status)) {
      currentRunStatusMessage.value = '连接断开，任务仍在后台运行'
      return
    }
    await loadHistory(conversationId, activeInitializeRequestId)
  } catch {
    if (conversation.value?.id === conversationId) {
      currentRunStatusMessage.value = '无法确认任务状态'
    }
  }
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

  const nextSocket = new WebSocket(buildConversationWebSocketUrl(conversationId))
  socket = nextSocket
  socketConversationId = conversationId

  nextSocket.onopen = () => {
    if (!isCurrentSocket(nextSocket, conversationId)) {
      return
    }
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

  nextSocket.onclose = () => {
    if (!isCurrentSocket(nextSocket, conversationId)) {
      return
    }
    connected.value = false
    void reconcileCurrentRun(conversationId)
    scheduleReconnect(conversationId)
  }

  nextSocket.onerror = () => {
    if (!isCurrentSocket(nextSocket, conversationId)) {
      return
    }
    connected.value = false
    void reconcileCurrentRun(conversationId)
    ElMessage.error('WebSocket 连接异常')
  }

  nextSocket.onmessage = async (event) => {
    if (!isCurrentSocket(nextSocket, conversationId)) {
      return
    }
    let payload: ServerWsMessage
    try {
      payload = JSON.parse(event.data) as ServerWsMessage
    } catch {
      ElMessage.error('WebSocket 消息解析失败')
      return
    }

    if (payload.type === 'assistant_delta') {
      if (!isCurrentSocket(nextSocket, conversationId)) {
        return
      }
      errorMessage.value = ''
      if (!activeAssistantMessageId.value) {
        activeAssistantMessageId.value = `assistant-${Date.now()}`
        messages.value.push({
          id: activeAssistantMessageId.value,
          run_id: currentRunId.value,
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
      if (!isCurrentSocket(nextSocket, conversationId)) {
        return
      }
      currentRunId.value = payload.run_id ?? currentRunId.value
      currentRunStatus.value =
        payload.status === 'done' ? 'success' : payload.status === 'idle' ? '' : payload.status
      currentRunStatusMessage.value = payload.message ?? ''
      if (payload.output_files) {
        outputFiles.value = payload.output_files
      }
      sending.value = isActiveRunStatus(currentRunStatus.value)
      if (!sending.value) {
        const target = messages.value.find((message) => message.id === activeAssistantMessageId.value)
        if (target) {
          target.streaming = false
        }
        activeAssistantMessageId.value = null
        if (conversation.value?.id === conversationId) {
          const requestId = activeInitializeRequestId
          await loadHistory(conversationId, requestId)
          if (!isCurrentSocket(nextSocket, conversationId)) {
            return
          }
          conversations.value = await fetchConversations()
        }
      }
      return
    }

    if (payload.type === 'assistant_done') {
      if (!isCurrentSocket(nextSocket, conversationId)) {
        return
      }
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
      if (conversation.value?.id === conversationId) {
        const requestId = activeInitializeRequestId
        await loadHistory(conversationId, requestId)
        if (!isCurrentSocket(nextSocket, conversationId)) {
          return
        }
        conversations.value = await fetchConversations()
      }
      return
    }

    if (payload.type === 'active_run') {
      if (!isCurrentSocket(nextSocket, conversationId)) {
        return
      }
      if (payload.active_run) {
        applyRunState(payload.active_run)
        currentRunStatusMessage.value = payload.message ?? '当前会话已有任务正在运行'
      } else {
        sending.value = false
        currentRunStatusMessage.value = payload.message ?? '当前会话已有任务正在运行'
      }
      ElMessage.warning(payload.message ?? '当前会话已有任务正在运行')
      return
    }

    if (!isCurrentSocket(nextSocket, conversationId)) {
      return
    }
    errorMessage.value = payload.message
    ElMessage.error(payload.message)
    const target = messages.value.find((message) => message.id === activeAssistantMessageId.value)
    if (target) {
      target.streaming = false
    }
    activeAssistantMessageId.value = null
    if (currentRunId.value) {
      void reconcileCurrentRun(conversationId)
    } else {
      sending.value = false
    }
  }
}

function closeActiveSocket() {
  clearReconnectTimer()
  if (socket) {
    socket.onclose = null
    socket.onerror = null
    socket.close()
    socket = null
  }
  socketConversationId = null
  connected.value = false
}

async function ensureConversation(
  currentAgent: Agent,
  requestId: number,
  preferredConversationId?: number,
) {
  if (preferredConversationId) {
    const selected = await loadHistory(preferredConversationId, requestId, currentAgent.id)
    if (selected) {
      return
    }
  }

  const existing = conversations.value.find((item) => item.agent_id === currentAgent.id)
  if (existing) {
    await loadHistory(existing.id, requestId, currentAgent.id)
    return
  }

  const created = await createConversation({
    agent_id: currentAgent.id,
    title: `${currentAgent.name} 对话`,
  })
  if (!isActiveInitializeRequest(requestId)) {
    return
  }
  conversations.value = [created, ...conversations.value]
  await loadHistory(created.id, requestId, currentAgent.id)
}

async function initializeAgent(agentCode: string, preferredConversationId?: number) {
  const requestId = ++activeInitializeRequestId
  closeActiveSocket()
  loading.value = true
  errorMessage.value = ''
  attachedFiles.value = []
  conversation.value = null
  resetConversationRuntimeState()
  messages.value = []

  try {
    if (agents.value.length === 0 || conversations.value.length === 0) {
      await refreshSidebarData(requestId)
    }
    if (!isActiveInitializeRequest(requestId)) {
      return
    }
    const currentAgent = agents.value.find((item) => item.code === agentCode) ?? (await fetchAgent(agentCode))
    if (!isActiveInitializeRequest(requestId)) {
      return
    }
    agent.value = currentAgent
    await ensureConversation(currentAgent, requestId, preferredConversationId)
    const initializedConversation = conversation.value as Conversation | null
    if (isActiveInitializeRequest(requestId) && initializedConversation) {
      connectWebSocket(initializedConversation.id)
    }
  } catch (error) {
    if (isActiveInitializeRequest(requestId)) {
      ElMessage.error('对话初始化失败')
      router.push({ name: 'agents' })
    }
  } finally {
    if (isActiveInitializeRequest(requestId)) {
      loading.value = false
    }
  }
}

async function selectAgent(nextAgent: Agent) {
  closeActiveSocket()
  conversation.value = null
  resetConversationRuntimeState()
  if (String(route.params.agentCode) === nextAgent.code) {
    await initializeAgent(nextAgent.code)
    return
  }
  router.push({ name: 'agent-chat', params: { agentCode: nextAgent.code }, query: {} })
}

function isConversationDeleteBlocked(nextConversation: Conversation) {
  return (
    nextConversation.id === conversation.value?.id &&
    (sending.value || isActiveRunStatus(currentRunStatus.value))
  )
}

function getDeleteConversationTooltip(nextConversation: Conversation) {
  return isConversationDeleteBlocked(nextConversation) ? '请先停止当前任务' : '删除历史对话'
}

async function createNewConversationForCurrentAgent() {
  if (!agent.value) {
    ElMessage.warning('请先选择 Agent')
    return
  }
  await createNewConversationForAgent(agent.value)
}

async function createNewConversationForAgent(nextAgent: Agent) {
  suppressRouteWatch = true
  closeActiveSocket()
  conversation.value = null
  resetConversationRuntimeState()
  attachedFiles.value = []
  errorMessage.value = ''
  try {
    const created = await createConversation({
      agent_id: nextAgent.id,
      title: `${nextAgent.name} 对话`,
    })
    conversations.value = [created, ...conversations.value.filter((item) => item.id !== created.id)]
    await router.push({
      name: 'agent-chat',
      params: { agentCode: nextAgent.code },
      query: { conversationId: String(created.id) },
    })
    await initializeAgent(nextAgent.code, created.id)
  } catch {
    ElMessage.error('新建对话失败')
  } finally {
    suppressRouteWatch = false
  }
}

async function deleteHistoryConversation(nextConversation: Conversation) {
  if (isConversationDeleteBlocked(nextConversation)) {
    ElMessage.warning('请先停止当前任务')
    return
  }

  try {
    await ElMessageBox.confirm('删除后该会话和消息将无法恢复，是否继续？', '删除历史对话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }

  const isDeletingCurrent = nextConversation.id === conversation.value?.id
  deletingConversationId.value = nextConversation.id
  try {
    await deleteConversation(nextConversation.id)
    const remainingConversations = conversations.value.filter((item) => item.id !== nextConversation.id)
    conversations.value = remainingConversations
    ElMessage.success('历史对话已删除')

    if (!isDeletingCurrent) {
      return
    }

    closeActiveSocket()
    conversation.value = null
    resetConversationRuntimeState()
    attachedFiles.value = []
    errorMessage.value = ''
    messages.value = []
    const nextConversationForAgent = remainingConversations.find(
      (item) => item.agent_id === nextConversation.agent_id,
    )
    if (nextConversationForAgent) {
      await selectConversation(nextConversationForAgent)
      return
    }

    const nextAgent =
      agents.value.find((item) => item.id === nextConversation.agent_id) ??
      (agent.value?.id === nextConversation.agent_id ? agent.value : null)
    if (nextAgent) {
      await createNewConversationForAgent(nextAgent)
    }
  } catch {
    ElMessage.error('删除历史对话失败')
  } finally {
    deletingConversationId.value = null
  }
}

async function selectConversation(nextConversation: Conversation) {
  suppressRouteWatch = true
  try {
    closeActiveSocket()
    conversation.value = null
    resetConversationRuntimeState()
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
  if (sending.value || isActiveRunStatus(currentRunStatus.value)) {
    ElMessage.warning('当前会话已有任务正在运行')
    return
  }
  if (
    !socket ||
    socket.readyState !== WebSocket.OPEN ||
    !conversation.value ||
    socketConversationId !== conversation.value.id
  ) {
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
    run_id: null,
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

async function stopCurrentRun() {
  if (!currentRunId.value || !conversation.value) {
    return
  }
  const runId = currentRunId.value
  const conversationId = conversation.value.id
  sending.value = false
  currentRunStatusMessage.value = '正在停止当前回复'
  try {
    const run = await cancelRun(runId)
    if (conversation.value?.id !== conversationId) {
      return
    }
    applyRunState(run)
    if (!isActiveRunStatus(run.status)) {
      const target = messages.value.find((message) => message.id === activeAssistantMessageId.value)
      if (target) {
        target.streaming = false
      }
      activeAssistantMessageId.value = null
      await loadHistory(conversationId, activeInitializeRequestId)
    } else {
      currentRunStatusMessage.value = '正在停止当前回复'
    }
  } catch {
    ElMessage.error('停止任务失败')
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
          <div
            v-for="item in agents"
            :key="item.code"
            class="agent-row"
            :class="{ active: item.code === agent?.code }"
          >
            <button class="list-item agent-select" type="button" @click="selectAgent(item)">
              <span>{{ item.name }}</span>
              <el-tag size="small" :type="riskTagType(item.risk_level)" effect="plain">
                {{ item.risk_level }}
              </el-tag>
            </button>
          </div>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="panel-header">
            <span>历史会话</span>
            <div class="panel-header-actions">
              <el-tag effect="plain">{{ conversationsByAgent.length }}</el-tag>
              <el-tooltip content="新建对话">
                <el-button
                  class="new-conversation-button"
                  :icon="Plus"
                  circle
                  plain
                  size="small"
                  :disabled="!agent"
                  @click="createNewConversationForCurrentAgent"
                />
              </el-tooltip>
            </div>
          </div>
        </template>
        <div class="conversation-list">
          <div
            v-for="item in conversationsByAgent"
            :key="item.id"
            class="conversation-row"
            :class="{ active: item.id === conversation?.id }"
          >
            <button class="list-item conversation-item" type="button" @click="selectConversation(item)">
              <span>{{ item.title }}</span>
              <small>{{ item.updated_at }}</small>
            </button>
            <el-tooltip :content="getDeleteConversationTooltip(item)">
              <span class="conversation-delete-wrapper">
                <el-button
                  class="delete-conversation-button"
                  :icon="Delete"
                  circle
                  plain
                  size="small"
                  type="danger"
                  :loading="deletingConversationId === item.id"
                  :disabled="isConversationDeleteBlocked(item) || deletingConversationId === item.id"
                  @click.stop="deleteHistoryConversation(item)"
                />
              </span>
            </el-tooltip>
          </div>
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
  grid-template-rows: minmax(0, 1fr);
  gap: 16px;
  align-items: stretch;
  height: 100%;
  max-height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.chat-panel {
  display: grid;
  align-content: start;
  gap: 16px;
  max-height: 100%;
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

.panel-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.agent-list,
.conversation-list,
.output-list {
  display: grid;
  gap: 8px;
}

.agent-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  align-items: center;
}

.agent-row:hover .agent-select,
.agent-row.active .agent-select {
  background: #dfe9fb;
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

.agent-select {
  border-radius: 20px;
}

.new-conversation-button {
  flex: 0 0 auto;
}

.list-item span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.conversation-row:hover .conversation-item,
.conversation-row.active .conversation-item {
  background: #dfe9fb;
}

.conversation-item {
  display: grid;
  justify-items: start;
  min-width: 0;
  border-radius: 12px;
}

.conversation-item small {
  color: #6f7785;
  font-size: 12px;
}

.conversation-delete-wrapper,
.delete-conversation-button {
  flex: 0 0 auto;
}

.chat-main {
  display: grid;
  grid-template-rows: minmax(0, 1fr);
  height: 100%;
  max-height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
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

  .chat-main {
    grid-template-rows: auto minmax(0, 1fr);
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
    grid-template-rows: auto minmax(0, 1fr);
    height: 100%;
    max-height: 100%;
  }

  .left-panel {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    max-height: 172px;
    overflow-y: auto;
  }

  .left-panel :deep(.el-card__header) {
    padding: 10px 12px;
  }

  .left-panel :deep(.el-card__body) {
    padding: 10px 12px;
  }

  .agent-list,
  .conversation-list {
    max-height: 92px;
    overflow-y: auto;
  }

  .list-item {
    min-height: 36px;
    padding: 7px 10px;
    border-radius: 10px;
  }
}

@media (max-width: 560px) {
  .left-panel {
    grid-template-columns: 1fr;
    max-height: 220px;
  }
}
</style>
