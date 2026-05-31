<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { fetchAgent, type Agent } from '../api/agents'
import {
  buildConversationWebSocketUrl,
  createConversation,
  fetchConversation,
  fetchConversations,
  type Conversation,
  type LocalMessage,
} from '../api/conversations'
import ChatWindow from '../components/ChatWindow.vue'
import { useAuthStore } from '../stores/auth'

type ServerWsMessage =
  | { type: 'assistant_delta'; content: string }
  | { type: 'assistant_done'; message_id: number }
  | { type: 'run_status'; status: string; message?: string }
  | { type: 'error'; message: string }

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const loading = ref(true)
const connected = ref(false)
const sending = ref(false)
const agent = ref<Agent | null>(null)
const conversation = ref<Conversation | null>(null)
const messages = ref<LocalMessage[]>([])
const activeAssistantMessageId = ref<string | null>(null)
const errorMessage = ref('')
const highRiskConfirmed = ref(false)
let socket: WebSocket | null = null

const title = computed(() => conversation.value?.title ?? agent.value?.name ?? 'Agent 对话')
const subtitle = computed(() => {
  if (!conversation.value) {
    return '正在准备会话'
  }
  return `${conversation.value.agent_name} · ${conversation.value.session_key}`
})

function normalizeMessages(serverMessages: Awaited<ReturnType<typeof fetchConversation>>['messages']) {
  messages.value = serverMessages.map((message) => ({ ...message, streaming: false }))
}

async function loadHistory(conversationId: number) {
  const detail = await fetchConversation(conversationId)
  conversation.value = detail
  normalizeMessages(detail.messages)
}

async function ensureConversation(currentAgent: Agent) {
  const conversations = await fetchConversations()
  const existing = conversations.find((item) => item.agent_id === currentAgent.id)
  if (existing) {
    conversation.value = existing
    await loadHistory(existing.id)
    return
  }

  const created = await createConversation({
    agent_id: currentAgent.id,
    title: `${currentAgent.name} 对话`,
  })
  conversation.value = created
  await loadHistory(created.id)
}

function connectWebSocket(conversationId: number) {
  socket?.close()
  socket = new WebSocket(buildConversationWebSocketUrl(conversationId))

  socket.onopen = () => {
    connected.value = true
    errorMessage.value = ''
  }

  socket.onclose = () => {
    connected.value = false
    sending.value = false
    ElMessage.warning('WebSocket 已断开')
  }

  socket.onerror = () => {
    connected.value = false
    sending.value = false
    ElMessage.error('WebSocket 连接异常')
  }

  socket.onmessage = async (event) => {
    const payload = JSON.parse(event.data) as ServerWsMessage
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
      sending.value = payload.status !== 'done' && payload.status !== 'idle'
      return
    }

    if (payload.type === 'assistant_done') {
      const target = messages.value.find((message) => message.id === activeAssistantMessageId.value)
      if (target) {
        target.id = payload.message_id
        target.streaming = false
      }
      activeAssistantMessageId.value = null
      sending.value = false
      if (conversation.value) {
        await loadHistory(conversation.value.id)
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

async function sendMessage(content: string) {
  if (!socket || socket.readyState !== WebSocket.OPEN || !conversation.value) {
    ElMessage.error('WebSocket 未连接')
    return
  }

  if (agent.value?.risk_level === 'high' && !highRiskConfirmed.value) {
    try {
      await ElMessageBox.confirm(
        '该 Agent 可能访问数据库、飞书或执行高风险操作，是否继续？',
        '高风险 Agent 确认',
        {
          confirmButtonText: '继续',
          cancelButtonText: '取消',
          type: 'warning',
        },
      )
      highRiskConfirmed.value = true
    } catch {
      return
    }
  }

  sending.value = true
  errorMessage.value = ''
  messages.value.push({
    id: `user-${Date.now()}`,
    conversation_id: conversation.value.id,
    role: 'user',
    content,
    created_at: new Date().toISOString(),
    streaming: false,
  })
  socket.send(
    JSON.stringify({
      type: 'user_message',
      content,
      file_ids: [],
    }),
  )
}

async function confirmHighRiskAgent(currentAgent: Agent) {
  if (currentAgent.risk_level !== 'high' || highRiskConfirmed.value) {
    return
  }

  await ElMessageBox.confirm(
    '该 Agent 可能访问数据库、飞书或执行高风险操作，是否继续？',
    '高风险 Agent 确认',
    {
      confirmButtonText: '继续',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
  highRiskConfirmed.value = true
}

async function initialize() {
  loading.value = true
  try {
    const agentCode = String(route.params.agentCode ?? '')
    if (!agentCode) {
      throw new Error('missing agent code')
    }

    agent.value = await fetchAgent(agentCode)
    await confirmHighRiskAgent(agent.value)
    await ensureConversation(agent.value)
    if (conversation.value) {
      connectWebSocket(conversation.value.id)
    }
  } catch (error) {
    if (String(error) === 'cancel') {
      router.push({ name: 'agents' })
      return
    }
    ElMessage.error('对话初始化失败')
    router.push({ name: 'agents' })
  } finally {
    loading.value = false
  }
}

function logout() {
  authStore.logout()
  router.push({ name: 'login' })
}

onMounted(initialize)

onBeforeUnmount(() => {
  socket?.close()
})
</script>

<template>
  <main class="chat-page">
    <nav class="topbar">
      <el-button @click="router.push({ name: 'agents' })">Agent 工作台</el-button>
      <el-button @click="logout">退出</el-button>
    </nav>

    <ChatWindow
      :title="title"
      :subtitle="subtitle"
      :messages="messages"
      :connected="connected"
      :sending="sending"
      :loading="loading"
      :error-message="errorMessage"
      @send="sendMessage"
    />
  </main>
</template>

<style scoped>
.chat-page {
  min-height: 100vh;
  padding: 24px;
  background: #eef2f7;
  color: #1f2937;
}

.topbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  width: min(1180px, 100%);
  margin: 0 auto 16px;
}

.chat-page :deep(.chat-window) {
  width: min(1180px, 100%);
  margin: 0 auto;
}

@media (max-width: 720px) {
  .chat-page {
    padding: 0;
  }

  .topbar {
    padding: 10px 12px;
    margin-bottom: 0;
    background: #ffffff;
    border-bottom: 1px solid #d9e2ec;
  }
}
</style>
