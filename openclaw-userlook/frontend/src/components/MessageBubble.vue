<script setup lang="ts">
import { computed } from 'vue'
import { CopyDocument, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import type { LocalMessage } from '../api/conversations'
import { downloadFile, formatFileSize, type UserFile } from '../api/files'
import { formatDateTimeShanghai } from '../utils/time'

const props = defineProps<{
  message: LocalMessage
  canStopRun?: boolean
}>()

const emit = defineEmits<{
  stopRun: [runId: number]
}>()

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderInlineMarkdown(value: string) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

function renderMarkdown(value: string) {
  const normalized = value.replace(/\r\n/g, '\n')
  const blocks: string[] = []
  let cursor = 0
  const fenceRe = /```([A-Za-z0-9_-]+)?\n([\s\S]*?)```/g
  let match: RegExpExecArray | null

  while ((match = fenceRe.exec(normalized))) {
    const before = normalized.slice(cursor, match.index)
    if (before) {
      blocks.push(`<p>${renderInlineMarkdown(before).replace(/\n/g, '<br>')}</p>`)
    }
    const language = match[1] ? ` data-language="${escapeHtml(match[1])}"` : ''
    blocks.push(`<pre><code${language}>${escapeHtml(match[2]).trimEnd()}</code></pre>`)
    cursor = match.index + match[0].length
  }

  const rest = normalized.slice(cursor)
  if (rest) {
    blocks.push(`<p>${renderInlineMarkdown(rest).replace(/\n/g, '<br>')}</p>`)
  }

  return blocks.join('')
}

const renderedContent = computed(() => renderMarkdown(props.message.content))
const canCopy = computed(() => props.message.role === 'assistant' && !props.message.streaming)

interface AttachmentDisplay {
  id: number | null
  name: string
  size: number | null
  file: UserFile | null
}

function toNumber(value: unknown): number | null {
  const numericValue = Number(value)
  return Number.isInteger(numericValue) && numericValue > 0 ? numericValue : null
}

function normalizeAttachment(value: unknown, index: number): AttachmentDisplay | null {
  if (!value || typeof value !== 'object') {
    const id = toNumber(value)
    return id ? { id, name: `文件 #${id}`, size: null, file: null } : null
  }
  const raw = value as Record<string, unknown>
  const id = toNumber(raw.id ?? raw.file_id)
  const name = String(raw.original_name ?? raw.name ?? raw.stored_name ?? (id ? `文件 #${id}` : `附件 ${index + 1}`))
  const sizeValue = Number(raw.file_size ?? raw.size)
  const size = Number.isFinite(sizeValue) && sizeValue >= 0 ? sizeValue : null
  const file = id
    ? ({
        id,
        user_id: Number(raw.user_id ?? 0),
        conversation_id: toNumber(raw.conversation_id),
        agent_code: typeof raw.agent_code === 'string' ? raw.agent_code : null,
        original_name: name,
        stored_name: typeof raw.stored_name === 'string' ? raw.stored_name : null,
        file_type: String(raw.file_type ?? ''),
        mime_type: typeof raw.mime_type === 'string' ? raw.mime_type : null,
        file_size: size ?? 0,
        sha256: typeof raw.sha256 === 'string' ? raw.sha256 : null,
        status: typeof raw.status === 'string' ? raw.status : 'ready',
        workspace_path: typeof raw.workspace_path === 'string' ? raw.workspace_path : null,
        purpose: 'upload',
        created_at: typeof raw.created_at === 'string' ? raw.created_at : props.message.created_at,
        updated_at: typeof raw.updated_at === 'string' ? raw.updated_at : null,
        download_url: typeof raw.download_url === 'string' ? raw.download_url : `/api/files/${id}/download`,
      } satisfies UserFile)
    : null
  return { id, name, size, file }
}

const attachments = computed(() => {
  if (props.message.role !== 'user') {
    return []
  }
  const rawPayload = props.message.raw_payload
  if (!rawPayload) {
    return []
  }
  const source = Array.isArray(rawPayload.attachments)
    ? rawPayload.attachments
    : Array.isArray(rawPayload.files)
      ? rawPayload.files
      : Array.isArray(rawPayload.file_ids)
        ? rawPayload.file_ids
        : []
  return source
    .map((item, index) => normalizeAttachment(item, index))
    .filter((item): item is AttachmentDisplay => Boolean(item))
})

async function copyMessageContent() {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(props.message.content)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = props.message.content
      textarea.style.position = 'fixed'
      textarea.style.left = '-9999px'
      document.body.appendChild(textarea)
      textarea.focus()
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

async function downloadAttachment(attachment: AttachmentDisplay) {
  if (!attachment.file) {
    return
  }
  await downloadFile(attachment.file)
}
</script>

<template>
  <div class="message-row" :class="`message-row--${message.role}`">
    <div class="message-bubble">
      <div class="message-meta">
        <span>{{ message.role === 'user' ? '我' : 'Agent' }}</span>
        <div class="message-meta__actions">
          <time>{{ formatDateTimeShanghai(message.created_at) }}</time>
          <el-tooltip v-if="canCopy" content="复制回复">
            <el-button
              class="copy-message-button"
              :icon="CopyDocument"
              circle
              plain
              size="small"
              @click="copyMessageContent"
            />
          </el-tooltip>
        </div>
      </div>
      <div class="message-content" v-html="renderedContent" />
      <div v-if="attachments.length" class="message-attachments">
        <el-button
          v-for="attachment in attachments"
          :key="attachment.id ?? attachment.name"
          link
          type="primary"
          :icon="Download"
          :disabled="!attachment.file"
          @click="downloadAttachment(attachment)"
        >
          {{ attachment.name }}<template v-if="attachment.size !== null"> · {{ formatFileSize(attachment.size) }}</template>
        </el-button>
      </div>
      <div v-if="message.streaming" class="message-status">
        <span>生成中</span>
        <el-button
          v-if="canStopRun && message.run_id"
          link
          size="small"
          type="warning"
          @click="emit('stopRun', message.run_id)"
        >
          停止
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.message-row {
  display: flex;
  width: 100%;
}

.message-row--user {
  justify-content: flex-end;
}

.message-row--assistant,
.message-row--system {
  justify-content: flex-start;
}

.message-bubble {
  width: fit-content;
  max-width: min(760px, 84%);
  min-width: 88px;
  padding: 12px 14px;
  border: 1px solid #dfe5ee;
  border-radius: 18px;
  background: #ffffff;
  color: #202124;
  box-shadow: 0 1px 2px rgb(60 64 67 / 8%);
}

.message-row--assistant .message-bubble,
.message-row--system .message-bubble {
  width: min(760px, 84%);
}

.message-row--user .message-bubble {
  max-width: min(520px, 72%);
  border-color: #dfe9fb;
  background: #dfe9fb;
}

.message-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
  color: #6f7785;
  font-size: 12px;
  font-weight: 700;
}

.message-meta time {
  font-weight: 400;
}

.message-meta__actions {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
}

.copy-message-button {
  width: 24px;
  height: 24px;
}

.message-content {
  line-height: 1.65;
  word-break: normal;
  overflow-wrap: break-word;
}

.message-content :deep(p) {
  margin: 0;
}

.message-content :deep(p + p) {
  margin-top: 10px;
}

.message-content :deep(code) {
  padding: 1px 5px;
  border-radius: 4px;
  background: rgb(15 23 42 / 8%);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92em;
}

.message-content :deep(pre) {
  margin: 10px 0 0;
  padding: 12px;
  border-radius: 8px;
  background: #0f172a;
  color: #e5e7eb;
  overflow-x: auto;
}

.message-content :deep(pre code) {
  display: block;
  padding: 0;
  background: transparent;
  color: inherit;
  white-space: pre;
}

.message-status {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #6f7785;
  font-size: 12px;
}

.message-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.message-attachments .el-button {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
