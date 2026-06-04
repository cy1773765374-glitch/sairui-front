<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Close, Connection, Promotion, VideoPause } from '@element-plus/icons-vue'

import { formatFileSize, type UserFile } from '../api/files'
import type { TaskRunStatus } from '../api/runs'
import type { LocalMessage } from '../api/conversations'
import FileUploader from './FileUploader.vue'
import MessageBubble from './MessageBubble.vue'

const props = defineProps<{
  title: string
  subtitle: string
  messages: LocalMessage[]
  connected: boolean
  sending: boolean
  loading: boolean
  errorMessage: string
  attachedFiles: UserFile[]
  runId: number | null
  runStatus: TaskRunStatus | ''
  runStatusMessage: string
  outputFiles: UserFile[]
  activeRunCount: number
}>()

const emit = defineEmits<{
  send: [content: string, fileIds: number[]]
  stop: []
  stopRun: [runId: number]
  fileUploaded: [file: UserFile]
  removeFile: [fileId: number]
}>()

const draft = ref('')
const scrollRef = ref<HTMLElement | null>(null)

const canSend = computed(() => props.connected && draft.value.trim().length > 0)
const canStop = computed(() => ['pending', 'queued', 'running', 'stale'].includes(props.runStatus))

function send() {
  const content = draft.value.trim()
  if (!content || !canSend.value) {
    return
  }
  draft.value = ''
  emit('send', content, props.attachedFiles.map((file) => file.id))
}

async function scrollToBottom() {
  await nextTick()
  if (scrollRef.value) {
    scrollRef.value.scrollTop = scrollRef.value.scrollHeight
  }
}

watch(
  () => props.messages.map((message) => `${message.id}:${message.content.length}`).join('|'),
  scrollToBottom,
)
</script>

<template>
  <section class="chat-window">
    <header class="chat-header">
      <div>
        <h1>{{ title }}</h1>
        <p>{{ subtitle }}</p>
      </div>
      <el-tag :type="connected ? 'success' : 'danger'" effect="plain">
        <el-icon><Connection /></el-icon>
        {{ connected ? '已连接' : '已断开' }}
      </el-tag>
    </header>

    <div ref="scrollRef" class="message-list">
      <el-alert
        v-if="errorMessage"
        class="chat-error"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
      />
      <el-skeleton v-if="loading" :rows="5" animated />
      <div v-else-if="messages.length === 0" class="empty-chat">
        <h2>{{ title }}</h2>
        <p>发送一条消息开始对话。</p>
      </div>
      <MessageBubble
        v-for="message in messages"
        v-else
        :key="message.id"
        :message="message"
        :can-stop-run="message.streaming && !!message.run_id"
        @stop-run="(runId) => emit('stopRun', runId)"
      />
    </div>

    <footer class="composer">
      <div v-if="sending" class="response-status">
        Agent 正在响应<template v-if="activeRunCount > 1">（{{ activeRunCount }} 个任务进行中）</template>
      </div>
      <div v-else-if="runStatusMessage" class="response-status">
        {{ runStatusMessage }}
      </div>
      <div class="attachment-row">
        <FileUploader @uploaded="(file) => emit('fileUploaded', file)" />
        <el-tag
          v-for="file in attachedFiles"
          :key="file.id"
          class="attachment-tag"
          closable
          @close="emit('removeFile', file.id)"
        >
          {{ file.original_name }} · {{ formatFileSize(file.file_size) }}
        </el-tag>
        <el-button
          v-if="attachedFiles.length"
          link
          :icon="Close"
          @click="attachedFiles.forEach((file) => emit('removeFile', file.id))"
        >
          清空
        </el-button>
      </div>
      <el-input
        v-model="draft"
        class="composer-input"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 5 }"
        resize="none"
        maxlength="2000"
        show-word-limit
        placeholder="输入消息，Enter 发送，Shift + Enter 换行"
        :disabled="!connected"
        @keydown.enter.exact.prevent="send"
      />
      <div class="composer-actions">
        <el-tooltip content="停止当前回复">
          <el-button :icon="VideoPause" :disabled="!canStop" @click="emit('stop')">停止</el-button>
        </el-tooltip>
        <el-button
          class="send-button"
          type="primary"
          :icon="Promotion"
          :disabled="!canSend"
          @click="send"
        >
          发送
        </el-button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.chat-window {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-height: 100%;
  min-height: 0;
  box-sizing: border-box;
  border: 1px solid #dfe5ee;
  border-radius: 8px;
  background: #f8fafc;
  overflow: hidden;
}

.chat-header {
  flex: 0 0 auto;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
  border-bottom: 1px solid #dfe5ee;
  background: #ffffff;
}

h1,
p {
  margin: 0;
}

h1 {
  font-size: 20px;
  line-height: 1.35;
}

p {
  margin-top: 6px;
  color: #6f7785;
}

.message-list {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: 0;
  max-height: 100%;
  min-height: 0;
  box-sizing: border-box;
  padding: 20px;
  overflow-y: auto;
}

.composer {
  position: sticky;
  bottom: 0;
  z-index: 2;
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: end;
  min-height: 112px;
  box-sizing: border-box;
  padding: 16px 20px;
  border-top: 1px solid #dfe5ee;
  background: #ffffff;
}

.chat-error,
.response-status,
.attachment-row {
  grid-column: 1 / -1;
}

.empty-chat {
  display: grid;
  flex: 1 1 auto;
  place-content: center;
  gap: 8px;
  min-height: 260px;
  color: #667085;
  text-align: center;
}

.empty-chat h2,
.empty-chat p {
  margin: 0;
}

.empty-chat h2 {
  color: #202124;
  font-size: 24px;
}

.response-status {
  min-height: 18px;
  color: #6f7785;
  font-size: 13px;
}

.attachment-row,
.composer-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.attachment-tag {
  max-width: 260px;
}

.attachment-tag :deep(.el-tag__content) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-input {
  min-width: 0;
}

.send-button {
  min-width: 96px;
}

@media (max-width: 760px) {
  .chat-window {
    height: 100%;
    min-height: 0;
  }

  .chat-header,
  .message-list,
  .composer {
    padding-left: 14px;
    padding-right: 14px;
  }

  .composer {
    grid-template-columns: 1fr;
  }

  .composer-actions {
    justify-content: flex-end;
  }
}
</style>
