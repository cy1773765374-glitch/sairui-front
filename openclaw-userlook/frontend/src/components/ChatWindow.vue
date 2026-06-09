<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Close, Connection, Download, Expand, Fold, Promotion, VideoPause } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { downloadFile, formatFileSize, type UserFile } from '../api/files'
import type { TaskRunStatus } from '../api/runs'
import type { LocalMessage } from '../api/conversations'
import FileUploader from './FileUploader.vue'
import MessageBubble from './MessageBubble.vue'

const props = defineProps<{
  title: string
  messages: LocalMessage[]
  connected: boolean
  sending: boolean
  loading: boolean
  errorMessage: string
  attachedFiles: UserFile[]
  agentCode?: string
  runId: number | null
  runStatus: TaskRunStatus | ''
  runStatusMessage: string
  runTaskKind?: string | null
  runnerName?: string | null
  runPhase?: string | null
  runProgressMessage?: string | null
  runDurationSeconds?: number | null
  outputFiles: UserFile[]
  activeRunCount: number
  canExport?: boolean
  chatSidebarCollapsed: boolean
}>()

const emit = defineEmits<{
  send: [content: string, fileIds: number[], clearDraft: () => void]
  stop: []
  stopRun: [runId: number]
  fileUploaded: [file: UserFile]
  removeFile: [fileId: number]
  exportConversation: []
  toggleChatSidebar: []
}>()

const draft = ref('')
const scrollRef = ref<HTMLElement | null>(null)
const uploadingFileCount = ref(0)

const filesUploading = computed(() => uploadingFileCount.value > 0)
const hasDraftOrFile = computed(() => draft.value.trim().length > 0 || props.attachedFiles.length > 0)
const canSend = computed(() => props.connected && !props.sending && !filesUploading.value && hasDraftOrFile.value)
const canStop = computed(() => props.runId !== null && ['queued', 'running'].includes(props.runStatus))
const isLongJob = computed(() => props.runTaskKind === 'long_job' || ['daoban_job', 'ppt_generation_job', 'mysql_analysis_job'].includes(props.runnerName || ''))
const jobElapsedLabel = computed(() => {
  const seconds = Math.max(0, Math.floor(props.runDurationSeconds ?? 0))
  const minutes = Math.floor(seconds / 60)
  const remaining = seconds % 60
  return minutes > 0 ? `${minutes}分${remaining}秒` : `${remaining}秒`
})
const jobStatusText = computed(() => {
  const parts: string[] = [props.runStatus || 'queued']
  if (props.runPhase) {
    parts.push(props.runPhase)
  }
  parts.push(`已运行 ${jobElapsedLabel.value}`)
  return parts.join(' · ')
})
const jobProgressText = computed(() => props.runProgressMessage || props.runStatusMessage)

function send() {
  const content = draft.value.trim()
  if (filesUploading.value) {
    ElMessage.warning('文件仍在上传中，请稍后再发送')
    return
  }
  if (!canSend.value) {
    return
  }
  emit('send', content, props.attachedFiles.map((file) => file.id), () => {
    if (draft.value.trim() === content) {
      draft.value = ''
    }
  })
}

function onUploadingChange(uploading: boolean) {
  uploadingFileCount.value = uploading ? 1 : 0
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
      <div class="chat-header__left">
        <el-tooltip :content="chatSidebarCollapsed ? '展开会话栏' : '收起会话栏'">
          <el-button
            :icon="chatSidebarCollapsed ? Expand : Fold"
            circle
            plain
            @click="emit('toggleChatSidebar')"
          />
        </el-tooltip>
      </div>
      <div class="chat-header__center">
        <h1>{{ title }}</h1>
      </div>
      <div class="chat-header__actions">
        <el-tooltip content="导出对话">
          <el-button
            :icon="Download"
            circle
            plain
            :disabled="!canExport"
            @click="emit('exportConversation')"
          />
        </el-tooltip>
        <el-tag :type="connected ? 'success' : 'danger'" effect="plain">
          <el-icon><Connection /></el-icon>
          {{ connected ? '已连接' : '已断开' }}
        </el-tag>
      </div>
    </header>

    <div ref="scrollRef" class="message-list">
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
      <el-alert
        v-if="errorMessage"
        class="composer-error"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
      />
      <div v-if="sending && isLongJob" class="response-status">
        <strong>{{ jobStatusText }}</strong>
        <span v-if="jobProgressText"> {{ jobProgressText }}</span>
      </div>
      <div v-if="sending && !isLongJob" class="response-status">
        <template v-if="runId">Agent 正在响应<template v-if="activeRunCount > 1">（{{ activeRunCount }} 个任务进行中）</template></template>
        <template v-else>正在发送消息</template>
      </div>
      <div v-if="!sending && runStatusMessage" class="response-status">
        {{ runStatusMessage }}
      </div>
      <div v-if="outputFiles.length" class="job-output-files">
        <el-button
          v-for="file in outputFiles"
          :key="file.id"
          link
          type="primary"
          :icon="Download"
          @click="downloadFile(file)"
        >
          {{ file.original_name }} ({{ formatFileSize(file.file_size) }})
        </el-button>
      </div>
      <div class="attachment-row">
        <FileUploader
          :agent-code="agentCode"
          @uploaded="(file) => emit('fileUploaded', file)"
          @uploading-change="onUploadingChange"
        />
        <el-tag v-if="filesUploading" effect="plain">文件上传中</el-tag>
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
  display: grid;
  grid-template-columns: minmax(120px, 1fr) auto minmax(120px, 1fr);
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  border-bottom: 1px solid #dfe5ee;
  background: #ffffff;
}

.chat-header__left {
  display: flex;
  justify-content: flex-start;
}

.chat-header__center {
  min-width: 0;
  justify-self: center;
  text-align: center;
}

.chat-header__actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-self: end;
  gap: 10px;
}

h1,
p {
  margin: 0;
}

h1 {
  font-size: 20px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.composer-error,
.response-status,
.job-output-files,
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
.job-output-files,
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

  .chat-header {
    grid-template-columns: auto minmax(0, 1fr) auto;
  }

  .composer {
    grid-template-columns: 1fr;
  }

  .composer-actions {
    justify-content: flex-end;
  }
}
</style>
