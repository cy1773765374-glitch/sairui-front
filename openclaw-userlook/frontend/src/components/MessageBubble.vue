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

.message-role {
  margin-bottom: 6px;
  color: #6f7785;
  font-size: 12px;
  font-weight: 700;
}

.message-content {
  white-space: pre-wrap;
  word-break: normal;
  overflow-wrap: break-word;
  line-height: 1.65;
}

.message-status {
  margin-top: 8px;
  color: #6f7785;
  font-size: 12px;
}
</style>
