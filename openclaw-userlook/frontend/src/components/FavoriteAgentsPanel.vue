<script setup lang="ts">
import { ref } from 'vue'
import { ChatDotRound, Close, Rank } from '@element-plus/icons-vue'

import type { FavoriteAgent } from '../api/favorites'

const props = defineProps<{
  favorites: FavoriteAgent[]
  loading?: boolean
}>()

const emit = defineEmits<{
  openChat: [agentCode: string]
  removeFavorite: [agentCode: string]
  reorder: [agentCodes: string[]]
}>()

const draggingCode = ref<string | null>(null)

function onDrop(targetCode: string) {
  const sourceCode = draggingCode.value
  draggingCode.value = null
  if (!sourceCode || sourceCode === targetCode) {
    return
  }
  const nextCodes = props.favorites.map((agent) => agent.agent_code)
  const fromIndex = nextCodes.indexOf(sourceCode)
  const toIndex = nextCodes.indexOf(targetCode)
  if (fromIndex < 0 || toIndex < 0) {
    return
  }
  nextCodes.splice(fromIndex, 1)
  nextCodes.splice(toIndex, 0, sourceCode)
  emit('reorder', nextCodes)
}
</script>

<template>
  <el-card class="favorite-panel" shadow="never">
    <template #header>
      <div class="favorite-panel__header">
        <span>我的常用</span>
        <el-tag effect="plain">{{ favorites.length }}</el-tag>
      </div>
    </template>

    <el-skeleton v-if="loading" :rows="4" animated />
    <el-empty v-else-if="favorites.length === 0" description="暂无收藏 Agent" />
    <div v-else class="favorite-list">
      <article
        v-for="agent in favorites"
        :key="agent.agent_code"
        class="favorite-item"
        :class="{ 'favorite-item--dragging': draggingCode === agent.agent_code }"
        draggable="true"
        @dragstart="draggingCode = agent.agent_code"
        @dragend="draggingCode = null"
        @dragover.prevent
        @drop.prevent="onDrop(agent.agent_code)"
      >
        <button class="favorite-item__main" type="button" @click="$emit('openChat', agent.agent_code)">
          <el-icon class="favorite-item__drag"><Rank /></el-icon>
          <span>
            <strong>{{ agent.name }}</strong>
            <small>{{ agent.description || agent.category || '点击进入对话' }}</small>
          </span>
        </button>
        <div class="favorite-item__actions">
          <el-button link type="primary" :icon="ChatDotRound" @click="$emit('openChat', agent.agent_code)">
            对话
          </el-button>
          <el-tooltip content="取消收藏">
            <el-button
              class="favorite-item__remove"
              :icon="Close"
              circle
              plain
              size="small"
              @click="$emit('removeFavorite', agent.agent_code)"
            />
          </el-tooltip>
        </div>
      </article>
    </div>
  </el-card>
</template>

<style scoped>
.favorite-panel {
  height: 100%;
  border-radius: 8px;
}

.favorite-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.favorite-list {
  display: grid;
  gap: 10px;
}

.favorite-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid #dfe5ee;
  border-radius: 8px;
  background: #ffffff;
}

.favorite-item--dragging {
  opacity: 0.62;
}

.favorite-item__main {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.favorite-item__drag {
  flex: 0 0 auto;
  color: #98a2b3;
  cursor: grab;
}

.favorite-item__main span {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.favorite-item__main strong,
.favorite-item__main small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.favorite-item__main small {
  color: #667085;
  font-size: 12px;
}

.favorite-item__actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

@media (max-width: 640px) {
  .favorite-item {
    grid-template-columns: 1fr;
  }

  .favorite-item__actions {
    justify-content: flex-end;
  }
}
</style>
