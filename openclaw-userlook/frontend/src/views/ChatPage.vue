<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, ArrowRight, Delete, EditPen, Expand, Fold, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'

import { fetchAgent, fetchAgents, type Agent } from '../api/agents'
import {
  buildConversationWebSocketUrl,
  createConversation,
  deleteConversation,
  fetchConversation,
  fetchConversations,
  updateConversationTitle,
  type Conversation,
  type LocalMessage,
} from '../api/conversations'
import { type UserFile } from '../api/files'
import { cancelRun, fetchRun, isActiveRunStatus, type TaskRun, type TaskRunStatus } from '../api/runs'
import ChatWindow from '../components/ChatWindow.vue'
import { formatDateTimeShanghai } from '../utils/time'

type ServerWsMessage =
  | {
      type: 'user_message_ack'
      conversation_id?: number
      run_id: number
      client_message_id?: string | null
      agent_code?: string | null
      openclaw_agent_id?: string | null
      gateway_session_key?: string | null
      status: TaskRunStatus | 'queued'
    }
  | {
      type: 'assistant_delta'
      conversation_id?: number
      run_id?: number
      client_message_id?: string | null
      message_id?: number | null
      content: string
    }
  | {
      type: 'assistant_done'
      conversation_id?: number
      message_id: number
      run_id?: number
      client_message_id?: string | null
      output_files?: UserFile[]
    }
  | {
      type: 'run_status'
      run_id?: number
      conversation_id?: number
      client_message_id?: string | null
      agent_code?: string | null
      openclaw_agent_id?: string | null
      gateway_session_key?: string | null
      queue_status?: 'queued' | 'immediate'
      status: TaskRunStatus | 'done' | 'idle'
      message?: string
      output_files?: UserFile[]
    }
  | { type: 'active_run'; conversation_id?: number; client_message_id?: string | null; message?: string; active_run: TaskRun | null }
  | {
      type: 'error'
      code?: string
      conversation_id?: number
      run_id?: number
      client_message_id?: string | null
      message: string
    }

interface ConversationRuntimeState {
  sending: boolean
  activeAssistantMessageId: string | number | null
  activeRunIds: number[]
  outputFiles: UserFile[]
  currentRunId: number | null
  currentClientMessageId: string | null
  currentRunStatus: TaskRunStatus | ''
  currentRunStatusMessage: string
}

interface ConversationAgentGroup {
  agent_code: string
  agent_name: string
  agent_id: number
  conversations: Conversation[]
}

const route = useRoute()
const router = useRouter()
const CHAT_SIDEBAR_COLLAPSED_KEY = 'sairui:chat-sidebar-collapsed'

const loading = ref(true)
const connected = ref(false)
const agents = ref<Agent[]>([])
const conversations = ref<Conversation[]>([])
const agent = ref<Agent | null>(null)
const conversation = ref<Conversation | null>(null)
const messages = ref<LocalMessage[]>([])
const messagesByConversation = ref<Record<number, LocalMessage[]>>({})
const activeRunByConversation = ref<Record<number, TaskRun | null>>({})
const errorMessage = ref('')
const attachedFiles = ref<UserFile[]>([])
const deletingConversationId = ref<number | null>(null)
const renamingConversationId = ref<number | null>(null)
const chatSidebarCollapsed = ref(localStorage.getItem(CHAT_SIDEBAR_COLLAPSED_KEY) === 'true')
const expandedAgentCodes = ref<string[]>([])
const runtimeByConversation = ref<Record<number, ConversationRuntimeState>>({})
const fallbackRuntime = ref<ConversationRuntimeState>(createRuntimeState())

let socket: WebSocket | null = null
let socketConversationId: number | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
const runPollingTimers = new Map<number, ReturnType<typeof setInterval>>()
const runPollingInFlight = new Set<number>()
let reconnectAttempts = 0
let unmounted = false
let suppressRouteWatch = false
let activeInitializeRequestId = 0

const title = computed(() => agent.value?.name ?? 'Agent 对话')
const subtitle = computed(() => {
  if (!conversation.value) {
    return '正在准备会话'
  }
  return conversation.value.title
})

const conversationGroups = computed<ConversationAgentGroup[]>(() => {
  const groups = new Map<string, ConversationAgentGroup>()
  conversations.value.forEach((item) => {
    const existing = groups.get(item.agent_code)
    if (existing) {
      existing.conversations.push(item)
      return
    }
    groups.set(item.agent_code, {
      agent_code: item.agent_code,
      agent_name: item.agent_name,
      agent_id: item.agent_id,
      conversations: [item],
    })
  })
  return Array.from(groups.values()).sort((left, right) => {
    if (left.agent_code === agent.value?.code) {
      return -1
    }
    if (right.agent_code === agent.value?.code) {
      return 1
    }
    const leftTime = Date.parse(left.conversations[0]?.updated_at ?? '')
    const rightTime = Date.parse(right.conversations[0]?.updated_at ?? '')
    return (Number.isNaN(rightTime) ? 0 : rightTime) - (Number.isNaN(leftTime) ? 0 : leftTime)
  })
})

const totalConversationCount = computed(() => conversations.value.length)

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
  set: (value: string | number | null) => {
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

const currentClientMessageId = computed({
  get: () => activeRuntime.value.currentClientMessageId,
  set: (value: string | null) => {
    activeRuntime.value.currentClientMessageId = value
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

const activeRunCount = computed(() => activeRuntime.value.activeRunIds.length)

function createRuntimeState(): ConversationRuntimeState {
  return {
    sending: false,
    activeAssistantMessageId: null,
    activeRunIds: [],
    outputFiles: [],
    currentRunId: null,
    currentClientMessageId: null,
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

function getMessagesForConversation(conversationId: number) {
  if (!messagesByConversation.value[conversationId]) {
    messagesByConversation.value[conversationId] = []
  }
  return messagesByConversation.value[conversationId]
}

function setMessagesForConversation(conversationId: number, nextMessages: LocalMessage[]) {
  messagesByConversation.value[conversationId] = nextMessages
  if (conversation.value?.id === conversationId) {
    messages.value = messagesByConversation.value[conversationId]
  }
}

function normalizeMessages(
  conversationId: number,
  serverMessages: Awaited<ReturnType<typeof fetchConversation>>['messages'],
  activeRun: TaskRun | null,
) {
  const normalized: LocalMessage[] = serverMessages.map((message) => ({ ...message, streaming: false }))
  const runtime = getRuntimeForConversation(conversationId)
  if (activeRun) {
    const assistantMessage = normalized.find(
      (message) => message.role === 'assistant' && message.run_id === activeRun.id,
    )
    if (assistantMessage) {
      assistantMessage.streaming = isActiveRunStatus(activeRun.status)
      runtime.activeAssistantMessageId = isActiveRunStatus(activeRun.status) ? assistantMessage.id : null
    } else if (activeRun.output_text) {
      const temporaryId = `assistant-run-${activeRun.id}`
      normalized.push({
        id: temporaryId,
        conversation_id: conversationId,
        run_id: activeRun.id,
        role: 'assistant',
        content: activeRun.output_text,
        created_at: activeRun.started_at || new Date().toISOString(),
        raw_payload: null,
        streaming: isActiveRunStatus(activeRun.status),
      })
      runtime.activeAssistantMessageId = isActiveRunStatus(activeRun.status) ? temporaryId : null
    }
  }
  setMessagesForConversation(conversationId, normalized)
}

function applyRunState(run: TaskRun | null) {
  const runtime =
    run?.conversation_id ? getRuntimeForConversation(run.conversation_id) : activeRuntime.value
  if (run?.conversation_id) {
    activeRunByConversation.value[run.conversation_id] = run
  }
  runtime.currentRunId = run?.id ?? null
  runtime.currentClientMessageId = run?.client_message_id ?? runtime.currentClientMessageId
  runtime.currentRunStatus = run?.status ?? ''
  runtime.currentRunStatusMessage = run?.error_message ?? ''
  runtime.outputFiles = run?.output_files ?? []
  if (run?.id && isActiveRunStatus(run.status)) {
    runtime.activeRunIds = Array.from(new Set([...runtime.activeRunIds, run.id]))
  } else if (run?.id) {
    runtime.activeRunIds = runtime.activeRunIds.filter((runId) => runId !== run.id)
  } else {
    runtime.activeRunIds = []
  }
  runtime.sending = runtime.activeRunIds.length > 0
  if (!runtime.sending) {
    runtime.activeAssistantMessageId = null
    if (run?.conversation_id) {
      stopRunPolling(run.conversation_id)
    }
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

function hasBlockingActiveRun() {
  return activeRuntime.value.activeRunIds.length > 0 || (currentRunId.value !== null && isActiveRunStatus(currentRunStatus.value))
}

function createClientMessageId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID()
  }
  const randomPart = Math.random().toString(36).slice(2, 10)
  return `web-${Date.now().toString(36)}-${randomPart}`
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
  activeRunByConversation.value[detail.id] = detail.active_run
  normalizeMessages(detail.id, detail.messages, detail.active_run)
  if (detail.active_run) {
    applyRunState(detail.active_run)
    if (isActiveRunStatus(detail.active_run.status)) {
      startRunPolling(detail.id)
    }
  } else {
    activeRunByConversation.value[detail.id] = null
    stopRunPolling(detail.id)
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

function stopRunPolling(conversationId?: number) {
  if (conversationId !== undefined) {
    const timer = runPollingTimers.get(conversationId)
    if (timer) {
      clearInterval(timer)
      runPollingTimers.delete(conversationId)
    }
    runPollingInFlight.delete(conversationId)
    return
  }
  runPollingTimers.forEach((timer) => clearInterval(timer))
  runPollingTimers.clear()
  runPollingInFlight.clear()
}

async function pollRunOnce(conversationId: number) {
  const runtime = getRuntimeForConversation(conversationId)
  const runId = runtime.currentRunId
  const clientMessageId = runtime.currentClientMessageId
  if (!runId || !isActiveRunStatus(runtime.currentRunStatus) || runPollingInFlight.has(conversationId)) {
    return
  }
  runPollingInFlight.add(conversationId)
  try {
    const run = await fetchRun(runId)
    if (run.conversation_id !== conversationId || run.id !== runId) {
      return
    }
    if (clientMessageId && run.client_message_id && run.client_message_id !== clientMessageId) {
      return
    }
    applyRunState(run)
    if (!isActiveRunStatus(run.status)) {
      stopRunPolling(conversationId)
      if (conversation.value?.id === conversationId) {
        await loadHistory(conversationId, activeInitializeRequestId)
      }
    }
  } catch {
    if (conversation.value?.id === conversationId) {
      currentRunStatusMessage.value = '无法确认任务状态'
    }
  } finally {
    runPollingInFlight.delete(conversationId)
  }
}

function startRunPolling(conversationId: number) {
  const runtime = getRuntimeForConversation(conversationId)
  if (!runtime.currentRunId || !isActiveRunStatus(runtime.currentRunStatus)) {
    return
  }
  if (runPollingTimers.has(conversationId)) {
    return
  }
  void pollRunOnce(conversationId)
  const timer = setInterval(() => {
    void pollRunOnce(conversationId)
  }, 1500)
  runPollingTimers.set(conversationId, timer)
}

function isCurrentSocket(currentSocket: WebSocket, conversationId: number) {
  return (
    !unmounted &&
    socket === currentSocket &&
    socketConversationId === conversationId &&
    conversation.value?.id === conversationId
  )
}

function isPayloadForConversation(
  payload: { conversation_id?: number; run_id?: number; client_message_id?: string | null },
  conversationId: number,
) {
  if (payload.conversation_id !== undefined && payload.conversation_id !== conversationId) {
    return false
  }
  return true
}

function findAssistantMessage(conversationId: number, messageId: string | number | null, runId?: number) {
  const list = getMessagesForConversation(conversationId)
  return list.find((message) => {
    if (runId !== undefined && message.role === 'assistant' && message.run_id === runId) {
      return true
    }
    if (messageId !== null && message.id === messageId) {
      return true
    }
    return false
  })
}

function markRunActive(conversationId: number, runId?: number) {
  if (runId === undefined) {
    return
  }
  const runtime = getRuntimeForConversation(conversationId)
  runtime.activeRunIds = Array.from(new Set([...runtime.activeRunIds, runId]))
  runtime.sending = true
}

function markRunInactive(conversationId: number, runId?: number) {
  const runtime = getRuntimeForConversation(conversationId)
  if (runId !== undefined) {
    runtime.activeRunIds = runtime.activeRunIds.filter((activeRunId) => activeRunId !== runId)
  }
  runtime.sending = runtime.activeRunIds.length > 0
}

function removeOptimisticUserMessage(conversationId: number, clientMessageId: string | null | undefined) {
  if (!clientMessageId) {
    return
  }
  setMessagesForConversation(
    conversationId,
    getMessagesForConversation(conversationId).filter((message) => message.id !== `user-${clientMessageId}`),
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
    currentRunId.value = null
    currentClientMessageId.value = null
    currentRunStatus.value = ''
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

    if (payload.type === 'user_message_ack') {
      if (!isCurrentSocket(nextSocket, conversationId) || !isPayloadForConversation(payload, conversationId)) {
        return
      }
      const runtime = getRuntimeForConversation(conversationId)
      runtime.currentRunId = payload.run_id
      runtime.currentClientMessageId = payload.client_message_id ?? runtime.currentClientMessageId
      runtime.currentRunStatus = payload.status === 'queued' ? 'queued' : payload.status
      runtime.currentRunStatusMessage = ''
      if (isActiveRunStatus(runtime.currentRunStatus)) {
        markRunActive(conversationId, payload.run_id)
      } else {
        markRunInactive(conversationId, payload.run_id)
      }
      if (runtime.sending) {
        startRunPolling(conversationId)
      }
      return
    }

    if (payload.type === 'assistant_delta') {
      if (!isCurrentSocket(nextSocket, conversationId) || !isPayloadForConversation(payload, conversationId)) {
        return
      }
      errorMessage.value = ''
      const runtime = getRuntimeForConversation(conversationId)
      currentRunId.value = payload.run_id ?? currentRunId.value
      currentClientMessageId.value = payload.client_message_id ?? currentClientMessageId.value
      markRunActive(conversationId, payload.run_id)
      let target = findAssistantMessage(conversationId, payload.message_id ?? null, payload.run_id)
      if (!target) {
        const temporaryId = payload.message_id ?? `assistant-run-${payload.run_id ?? Date.now()}`
        runtime.activeAssistantMessageId = temporaryId
        target = {
          id: temporaryId,
          conversation_id: conversationId,
          run_id: payload.run_id ?? currentRunId.value,
          role: 'assistant',
          content: '',
          created_at: new Date().toISOString(),
          raw_payload: null,
          streaming: true,
        }
        getMessagesForConversation(conversationId).push(target)
      }

      target.content += payload.content
      target.streaming = true
      if (payload.message_id) {
        target.id = payload.message_id
        runtime.activeAssistantMessageId = payload.message_id
      }
      return
    }

    if (payload.type === 'run_status') {
      if (!isCurrentSocket(nextSocket, conversationId) || !isPayloadForConversation(payload, conversationId)) {
        return
      }
      currentRunId.value = payload.run_id ?? currentRunId.value
      currentClientMessageId.value = payload.client_message_id ?? currentClientMessageId.value
      currentRunStatus.value =
        payload.status === 'done' ? 'success' : payload.status === 'idle' ? '' : payload.status
      currentRunStatusMessage.value = payload.message ?? ''
      if (payload.output_files) {
        outputFiles.value = payload.output_files
      }
      if (isActiveRunStatus(currentRunStatus.value)) {
        markRunActive(conversationId, payload.run_id)
      } else {
        markRunInactive(conversationId, payload.run_id)
      }
      if (sending.value) {
        startRunPolling(conversationId)
      }
      if (!isActiveRunStatus(currentRunStatus.value)) {
        const target = findAssistantMessage(conversationId, null, payload.run_id ?? currentRunId.value ?? undefined)
        if (target) {
          target.streaming = false
        }
        if (!sending.value) {
          stopRunPolling(conversationId)
          activeAssistantMessageId.value = null
        }
        if (!sending.value && conversation.value?.id === conversationId) {
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
      if (!isCurrentSocket(nextSocket, conversationId) || !isPayloadForConversation(payload, conversationId)) {
        return
      }
      currentRunId.value = payload.run_id ?? currentRunId.value
      currentClientMessageId.value = payload.client_message_id ?? currentClientMessageId.value
      if (payload.output_files) {
        outputFiles.value = payload.output_files
      }
      const target = findAssistantMessage(conversationId, payload.message_id, payload.run_id)
      if (target) {
        target.id = payload.message_id
        target.streaming = false
      }
      markRunInactive(conversationId, payload.run_id)
      if (!sending.value) {
        activeAssistantMessageId.value = null
        stopRunPolling(conversationId)
      }
      if (!sending.value && conversation.value?.id === conversationId) {
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
        currentRunId.value = null
        currentClientMessageId.value = null
        currentRunStatus.value = ''
        currentRunStatusMessage.value = payload.message ?? '当前会话已有任务正在运行'
      }
      ElMessage.warning(payload.message ?? '当前会话已有任务正在运行')
      return
    }

    if (!isCurrentSocket(nextSocket, conversationId)) {
      return
    }
    if (payload.code === 'invalid_file_ids' || payload.message === 'invalid file_ids') {
      attachedFiles.value = []
      removeOptimisticUserMessage(conversationId, payload.client_message_id)
    }
    errorMessage.value = payload.message
    ElMessage.error(payload.message)
    const errorRunId = payload.run_id ?? currentRunId.value ?? undefined
    const target = findAssistantMessage(conversationId, null, errorRunId)
    if (target) {
      target.streaming = false
    }
    if (payload.run_id !== undefined) {
      markRunInactive(conversationId, payload.run_id)
    } else if (activeRuntime.value.activeRunIds.length === 0) {
      sending.value = false
    }
    if (!sending.value) {
      activeAssistantMessageId.value = null
    }
    if (payload.run_id !== undefined) {
      void reconcileCurrentRun(conversationId)
    } else if (!sending.value) {
      currentClientMessageId.value = null
      currentRunStatus.value = ''
    }
  }
}

function closeActiveSocket() {
  clearReconnectTimer()
  if (socketConversationId !== null) {
    stopRunPolling(socketConversationId)
  }
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

function isConversationDeleteBlocked(nextConversation: Conversation) {
  return (
    nextConversation.id === conversation.value?.id &&
    (sending.value || hasBlockingActiveRun())
  )
}

function getDeleteConversationTooltip(nextConversation: Conversation) {
  return isConversationDeleteBlocked(nextConversation) ? '请先停止当前任务' : '删除历史对话'
}

function toggleChatSidebar() {
  chatSidebarCollapsed.value = !chatSidebarCollapsed.value
  localStorage.setItem(CHAT_SIDEBAR_COLLAPSED_KEY, String(chatSidebarCollapsed.value))
}

function isAgentGroupExpanded(agentCode: string) {
  return expandedAgentCodes.value.includes(agentCode)
}

function toggleAgentGroup(agentCode: string) {
  if (isAgentGroupExpanded(agentCode)) {
    expandedAgentCodes.value = expandedAgentCodes.value.filter((item) => item !== agentCode)
    return
  }
  expandedAgentCodes.value = [...expandedAgentCodes.value, agentCode]
}

function ensureAgentGroupExpanded(agentCode: string) {
  if (!expandedAgentCodes.value.includes(agentCode)) {
    expandedAgentCodes.value = [...expandedAgentCodes.value, agentCode]
  }
}

async function findAgentByCode(agentCode: string) {
  const cached = agents.value.find((item) => item.code === agentCode)
  if (cached) {
    return cached
  }
  const fetched = await fetchAgent(agentCode)
  agents.value = [fetched, ...agents.value.filter((item) => item.code !== fetched.code)]
  return fetched
}

function replaceConversationInList(nextConversation: Conversation) {
  conversations.value = conversations.value.map((item) =>
    item.id === nextConversation.id ? { ...item, ...nextConversation } : item,
  )
  if (conversation.value?.id === nextConversation.id) {
    conversation.value = { ...conversation.value, ...nextConversation }
  }
}

async function createNewConversationForCurrentAgent() {
  if (!agent.value) {
    ElMessage.warning('请先选择 Agent')
    return
  }
  await createNewConversationForAgent(agent.value)
}

async function createNewConversationForAgentCode(agentCode: string) {
  try {
    const nextAgent = await findAgentByCode(agentCode)
    await createNewConversationForAgent(nextAgent)
  } catch {
    ElMessage.error('新建对话失败')
  }
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

async function renameConversation(nextConversation: Conversation) {
  renamingConversationId.value = nextConversation.id
  try {
    const { value } = await ElMessageBox.prompt('请输入新的会话名称', '重命名会话', {
      inputValue: nextConversation.title,
      inputPlaceholder: '最多 20 个字符',
      inputPattern: /\S/,
      inputErrorMessage: '会话名称不能为空',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    const updated = await updateConversationTitle(nextConversation.id, { title: value })
    replaceConversationInList(updated)
    ElMessage.success('会话名称已更新')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error('重命名会话失败')
    }
  } finally {
    renamingConversationId.value = null
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
    delete messagesByConversation.value[nextConversation.id]
    delete runtimeByConversation.value[nextConversation.id]
    delete activeRunByConversation.value[nextConversation.id]
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
  if (
    !socket ||
    socket.readyState !== WebSocket.OPEN ||
    !conversation.value ||
    socketConversationId !== conversation.value.id
  ) {
    ElMessage.error('WebSocket 未连接')
    return
  }

  const clientMessageId = createClientMessageId()
  sending.value = true
  errorMessage.value = ''
  outputFiles.value = []
  currentRunId.value = null
  currentClientMessageId.value = clientMessageId
  currentRunStatus.value = 'queued'
  currentRunStatusMessage.value = ''
  getMessagesForConversation(conversation.value.id).push({
    id: `user-${clientMessageId}`,
    conversation_id: conversation.value.id,
    run_id: null,
    role: 'user',
    content,
    created_at: new Date().toISOString(),
    raw_payload: { file_ids: fileIds, client_message_id: clientMessageId },
    streaming: false,
  })
  messages.value = getMessagesForConversation(conversation.value.id)

  try {
    socket.send(
      JSON.stringify({
        type: 'user_message',
        content,
        file_ids: fileIds,
        client_message_id: clientMessageId,
      }),
    )
    attachedFiles.value = []
  } catch {
    sending.value = false
    currentRunId.value = null
    currentClientMessageId.value = null
    currentRunStatus.value = ''
    ElMessage.error('消息发送失败')
  }
}

async function stopRun(runId: number) {
  if (!conversation.value) {
    return
  }
  const conversationId = conversation.value.id
  currentRunStatusMessage.value = '正在停止当前回复'
  try {
    const run = await cancelRun(runId)
    if (conversation.value?.id !== conversationId) {
      return
    }
    applyRunState(run)
    if (!isActiveRunStatus(run.status)) {
      const target = findAssistantMessage(conversationId, null, runId)
      if (target) {
        target.streaming = false
      }
      if (!getRuntimeForConversation(conversationId).sending) {
        activeAssistantMessageId.value = null
        await loadHistory(conversationId, activeInitializeRequestId)
      }
    } else {
      currentRunStatusMessage.value = '正在停止当前回复'
    }
  } catch {
    ElMessage.error('停止任务失败')
  }
}

async function stopCurrentRun() {
  if (!currentRunId.value) {
    return
  }
  await stopRun(currentRunId.value)
}

function addUploadedFile(file: UserFile) {
  if (!attachedFiles.value.some((item) => item.id === file.id)) {
    attachedFiles.value.push(file)
  }
}

function removeAttachedFile(fileId: number) {
  attachedFiles.value = attachedFiles.value.filter((file) => file.id !== fileId)
}

function sanitizeFilenamePart(value: string) {
  return value.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '').replace(/\s+/g, ' ').trim() || '未命名会话'
}

function downloadMarkdown(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

async function exportCurrentConversation() {
  if (!conversation.value) {
    ElMessage.warning('暂无可导出的会话')
    return
  }
  try {
    const detail = await fetchConversation(conversation.value.id)
    const exportedAt = formatDateTimeShanghai(new Date().toISOString())
    const timestamp = exportedAt.replace(/-/g, '').replace(/:/g, '').replace(' ', '-')
    const safeTitle = sanitizeFilenamePart(detail.title)
    const filename = `赛锐Agent-${safeTitle}-${timestamp}.md`
    const lines = [
      '# 赛锐Agent 对话导出',
      '',
      `- Agent：${detail.agent_name}`,
      `- 会话：${detail.title}`,
      `- 导出时间：${exportedAt}`,
      '',
      '---',
      '',
    ]
    detail.messages.forEach((message) => {
      const role = message.role === 'user' ? '用户' : message.role === 'assistant' ? 'Agent' : '系统'
      lines.push(`## ${role} ${formatDateTimeShanghai(message.created_at)}`, '', message.content, '')
    })
    downloadMarkdown(filename, lines.join('\n'))
    ElMessage.success('对话已导出')
  } catch {
    ElMessage.error('导出对话失败')
  }
}

watch(
  () => [route.params.agentCode, route.query.conversationId],
  ([agentCode, conversationId]) => {
    if (!suppressRouteWatch && agentCode) {
      initializeAgent(String(agentCode), parseConversationId(conversationId))
    }
  },
)

watch(
  () => agent.value?.code,
  (agentCode) => {
    if (agentCode) {
      ensureAgentGroupExpanded(agentCode)
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
  stopRunPolling()
  if (socket) {
    socket.onclose = null
    socket.onerror = null
    socket.close()
  }
})
</script>

<template>
  <section class="chat-page" :class="{ 'chat-page--sidebar-collapsed': chatSidebarCollapsed }">
    <aside class="chat-panel left-panel" :class="{ 'left-panel--collapsed': chatSidebarCollapsed }">
      <div v-if="chatSidebarCollapsed" class="collapsed-chat-sidebar">
        <el-tooltip content="展开会话栏">
          <el-button :icon="Expand" circle plain @click="toggleChatSidebar" />
        </el-tooltip>
      </div>

      <el-card v-else shadow="never">
        <template #header>
          <div class="panel-header panel-header--stacked">
            <div>
              <strong>{{ agent?.name || 'Agent 对话' }}</strong>
              <small>{{ connected ? '已连接' : '连接中' }}</small>
            </div>
            <div class="panel-header-actions">
              <el-tag effect="plain">{{ totalConversationCount }}</el-tag>
              <el-tooltip content="新建当前 Agent 对话">
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
              <el-tooltip content="收起会话栏">
                <el-button :icon="Fold" circle plain size="small" @click="toggleChatSidebar" />
              </el-tooltip>
            </div>
          </div>
        </template>

        <div class="agent-group-list">
          <section
            v-for="group in conversationGroups"
            :key="group.agent_code"
            class="agent-group"
            :class="{ 'agent-group--current': group.agent_code === agent?.code }"
          >
            <header class="agent-group__header">
              <button class="agent-group__toggle" type="button" @click="toggleAgentGroup(group.agent_code)">
                <el-icon><component :is="isAgentGroupExpanded(group.agent_code) ? ArrowDown : ArrowRight" /></el-icon>
                <span>{{ group.agent_name }}</span>
                <small>{{ group.conversations.length }}</small>
              </button>
              <el-tooltip content="新建该 Agent 对话">
                <el-button
                  :icon="Plus"
                  circle
                  plain
                  size="small"
                  @click.stop="createNewConversationForAgentCode(group.agent_code)"
                />
              </el-tooltip>
            </header>

            <div v-show="isAgentGroupExpanded(group.agent_code)" class="conversation-list">
              <div
                v-for="item in group.conversations"
                :key="item.id"
                class="conversation-row"
                :class="{ active: item.id === conversation?.id }"
              >
                <button class="list-item conversation-item" type="button" @click="selectConversation(item)">
                  <span>{{ item.title }}</span>
                  <small>{{ formatDateTimeShanghai(item.updated_at) }}</small>
                </button>
                <div class="conversation-actions">
                  <el-tooltip content="重命名">
                    <el-button
                      class="rename-conversation-button"
                      :icon="EditPen"
                      circle
                      plain
                      size="small"
                      :loading="renamingConversationId === item.id"
                      :disabled="renamingConversationId === item.id"
                      @click.stop="renameConversation(item)"
                    />
                  </el-tooltip>
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
              </div>
            </div>
          </section>
          <el-empty v-if="conversationGroups.length === 0" description="暂无历史会话" />
        </div>
      </el-card>
    </aside>

    <main class="chat-main">
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
        :active-run-count="activeRunCount"
        :can-export="!!conversation"
        @send="sendMessage"
        @stop="stopCurrentRun"
        @stop-run="stopRun"
        @file-uploaded="addUploadedFile"
        @remove-file="removeAttachedFile"
        @export-conversation="exportCurrentConversation"
      />
    </main>
  </section>
</template>

<style scoped>
.chat-page {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  gap: 16px;
  align-items: stretch;
  height: 100%;
  max-height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.chat-page--sidebar-collapsed {
  grid-template-columns: 52px minmax(0, 1fr);
}

.chat-panel {
  display: grid;
  align-content: start;
  gap: 16px;
  max-height: 100%;
  min-height: 0;
  overflow-y: auto;
}

.left-panel--collapsed {
  overflow: hidden;
}

.collapsed-chat-sidebar {
  display: grid;
  min-height: 52px;
  place-items: center;
  border: 1px solid #dfe5ee;
  border-radius: 8px;
  background: #ffffff;
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

.panel-header--stacked {
  align-items: flex-start;
}

.panel-header--stacked > div:first-child {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.panel-header--stacked strong,
.panel-header--stacked small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-header--stacked small {
  color: #6f7785;
  font-size: 12px;
}

.panel-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.agent-group-list {
  display: grid;
  gap: 12px;
}

.agent-group {
  display: grid;
  gap: 8px;
}

.agent-group + .agent-group {
  padding-top: 12px;
  border-top: 1px solid #edf1f7;
}

.agent-group__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.agent-group__toggle {
  display: flex;
  min-width: 0;
  flex: 1 1 auto;
  align-items: center;
  gap: 6px;
  padding: 6px 4px;
  border: 0;
  background: transparent;
  color: #3c4043;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.agent-group__toggle span {
  min-width: 0;
  overflow: hidden;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-group__toggle small {
  flex: 0 0 auto;
  color: #6f7785;
  font-size: 12px;
}

.agent-group--current .agent-group__toggle {
  color: #174ea6;
}

.conversation-list {
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
.delete-conversation-button,
.rename-conversation-button {
  flex: 0 0 auto;
}

.conversation-actions {
  display: flex;
  align-items: center;
  gap: 6px;
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

@media (max-width: 1180px) {
  .chat-page {
    grid-template-columns: 260px minmax(0, 1fr);
  }

  .chat-page--sidebar-collapsed {
    grid-template-columns: 52px minmax(0, 1fr);
  }
}

@media (max-width: 820px) {
  .chat-page {
    grid-template-columns: 1fr;
    grid-template-rows: auto minmax(0, 1fr);
    height: 100%;
    max-height: 100%;
  }

  .chat-page--sidebar-collapsed {
    grid-template-columns: 1fr;
  }

  .left-panel {
    max-height: 180px;
    overflow-y: auto;
  }

  .left-panel--collapsed {
    max-height: 52px;
  }

  .collapsed-chat-sidebar {
    min-height: 44px;
  }

  .left-panel :deep(.el-card__header) {
    padding: 10px 12px;
  }

  .left-panel :deep(.el-card__body) {
    padding: 10px 12px;
  }

  .conversation-list {
    max-height: 160px;
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
    max-height: 220px;
  }
}
</style>
