<script setup lang="ts">
import type { Agent } from '../api/agents'

defineProps<{
  agent: Agent
}>()

defineEmits<{
  'open-chat': [agent: Agent]
}>()
</script>

<template>
  <button class="agent-card" type="button" @click="$emit('open-chat', agent)">
    <span>{{ agent.name }}</span>
  </button>
</template>

<style scoped>
.agent-card {
  display: flex;
  width: 100%;
  min-height: 92px;
  align-items: center;
  justify-content: center;
  padding: 18px 20px;
  border: 1px solid #dfe5ee;
  border-radius: 8px;
  background: #ffffff;
  color: #202124;
  cursor: pointer;
  font: inherit;
  text-align: center;
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease,
    transform 0.15s ease;
}

.agent-card:hover,
.agent-card:focus-visible {
  border-color: #1a73e8;
  box-shadow: 0 8px 22px rgb(60 64 67 / 10%);
  outline: none;
  transform: translateY(-1px);
}

.agent-card span {
  overflow-wrap: anywhere;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.35;
}
</style>
