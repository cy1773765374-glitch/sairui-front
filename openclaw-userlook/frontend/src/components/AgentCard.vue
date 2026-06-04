<script setup lang="ts">
import { Star, StarFilled } from '@element-plus/icons-vue'

import type { Agent } from '../api/agents'

defineProps<{
  agent: Agent
  favorited?: boolean
}>()

defineEmits<{
  'open-chat': [agent: Agent]
  'toggle-favorite': [agent: Agent]
}>()
</script>

<template>
  <article class="agent-card">
    <button class="agent-card__main" type="button" @click="$emit('open-chat', agent)">
      <span>{{ agent.name }}</span>
    </button>
    <el-tooltip :content="favorited ? '取消收藏' : '加入常用'">
      <el-button
        class="agent-card__favorite"
        :class="{ active: favorited }"
        :icon="favorited ? StarFilled : Star"
        circle
        plain
        size="small"
        @click.stop="$emit('toggle-favorite', agent)"
      />
    </el-tooltip>
  </article>
</template>

<style scoped>
.agent-card {
  position: relative;
  display: grid;
  width: 100%;
  min-height: 92px;
  border: 1px solid #dfe5ee;
  border-radius: 8px;
  background: #ffffff;
  color: #202124;
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease,
    transform 0.15s ease;
}

.agent-card:hover,
.agent-card:focus-within {
  border-color: #1a73e8;
  box-shadow: 0 8px 22px rgb(60 64 67 / 10%);
  outline: none;
  transform: translateY(-1px);
}

.agent-card__main {
  display: grid;
  width: 100%;
  min-height: 92px;
  place-items: center;
  padding: 18px 42px 18px 20px;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: center;
}

.agent-card__main span {
  overflow-wrap: anywhere;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.35;
}

.agent-card__favorite {
  position: absolute;
  top: 10px;
  right: 10px;
}

.agent-card__favorite.active {
  color: #f59e0b;
}
</style>
