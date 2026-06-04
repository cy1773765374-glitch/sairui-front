<script setup lang="ts">
import { AGENT_GROUPS, type AgentGroup } from '../utils/agentGroup'

defineProps<{
  modelValue: AgentGroup
}>()

const emit = defineEmits<{
  'update:modelValue': [value: AgentGroup]
}>()

function updateValue(value: string | number) {
  if (typeof value === 'string') {
    emit('update:modelValue', value as AgentGroup)
  }
}
</script>

<template>
  <el-segmented
    class="agent-category-tabs"
    :model-value="modelValue"
    :options="[...AGENT_GROUPS]"
    @update:model-value="updateValue"
  />
</template>

<style scoped>
.agent-category-tabs {
  max-width: 100%;
  overflow-x: auto;
}
</style>
