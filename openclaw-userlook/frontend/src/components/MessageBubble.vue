<script setup lang="ts">
import type { LocalMessage } from '../api/conversations'

defineProps<{
  message: LocalMessage
}>()
</script>

<template>
  <div class="message-row" :class="`message-row--${message.role}`">
    <div class="message-bubble">
      <div class="message-role">{{ message.role === 'user' ? '我' : 'Agent' }}</div>
      <div class="message-content">{{ message.content }}</div>
      <div v-if="message.streaming" class="message-status">生成中</div>
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
  max-width: min(680px, 84%);
  padding: 12px 14px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #ffffff;
  color: #1f2937;
  box-shadow: 0 1px 2px rgb(16 24 40 / 6%);
}

.message-row--user .message-bubble {
  border-color: #2563eb;
  background: #2563eb;
  color: #ffffff;
}

.message-role {
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 700;
  opacity: 0.72;
}

.message-content {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.6;
}

.message-status {
  margin-top: 8px;
  font-size: 12px;
  opacity: 0.68;
}
</style>
