<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Close, Connection, Promotion } from '@element-plus/icons-vue'

import { formatFileSize, type UserFile } from '../api/files'
import type { TaskRunStatus } from '../api/runs'
import type { LocalMessage } from '../api/conversations'
import FileUploader from './FileUploader.vue'
import MessageBubble from './MessageBubble.vue'
import RunStatus from './RunStatus.vue'

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
}>()

const emit = defineEmits<{
  send: [content: string, fileIds: number[]]
  fileUploaded: [file: UserFile]
  removeFile: [fileId: number]
}>()

const draft = ref('')
const scrollRef = ref<HTMLElement | null>(null)

const canSend = computed(() => props.connected && !props.sending && draft.value.trim().length > 0)

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

    <RunStatus
      :run-id="runId"
      :status="runStatus"
      :message="runStatusMessage"
      :output-files="outputFiles"
    />

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
      <el-empty v-else-if="messages.length === 0" description="暂无消息，发送一句开始对话。" />
      <MessageBubble
        v-for="message in messages"
        v-else
        :key="message.id"
        :message="message"
      />
    </div>

    <footer class="composer">
      <div v-if="sending" class="response-status">Agent 正在响应</div>
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
        placeholder="输入消息"
        :disabled="!connected || sending"
        @keydown.enter.exact.prevent="send"
      />
      <el-button
        class="send-button"
        type="primary"
        :icon="Promotion"
        :disabled="!canSend"
        :loading="sending"
        @click="send"
      >
        发送
      </el-button>
    </footer>
  </section>
</template>

<style scoped>
.chat-window {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  height: calc(100vh - 96px);
  min-height: 560px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #f8fafc;
  overflow: hidden;
}

.chat-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
  border-bottom: 1px solid #d9e2ec;
  background: #ffffff;
}

h1 {
  margin: 0;
  font-size: 20px;
  line-height: 1.35;
}

p {
  margin: 6px 0 0;
  color: #667085;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
  padding: 20px;
  overflow-y: auto;
}

.composer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: end;
  padding: 16px 20px;
  border-top: 1px solid #d9e2ec;
  background: #ffffff;
}

.chat-error {
  flex: 0 0 auto;
}

.response-status {
  grid-column: 1 / -1;
  min-height: 18px;
  color: #667085;
  font-size: 13px;
  line-height: 18px;
}

.attachment-row {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
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

@media (max-width: 720px) {
  .chat-window {
    height: calc(100vh - 56px);
    min-height: 480px;
    border-radius: 0;
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

  .send-button {
    width: 100%;
  }
}
</style>
