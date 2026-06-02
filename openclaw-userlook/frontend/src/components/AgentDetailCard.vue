<script setup lang="ts">
import { ChatDotRound, Files, Picture } from '@element-plus/icons-vue'

import type { Agent, AgentRiskLevel } from '../api/agents'

defineProps<{
  agent: Agent
}>()

defineEmits<{
  'open-chat': [agent: Agent]
}>()

function riskTagType(riskLevel: AgentRiskLevel) {
  if (riskLevel === 'high') {
    return 'danger'
  }
  if (riskLevel === 'medium') {
    return 'warning'
  }
  return 'success'
}
</script>

<template>
  <el-card class="agent-card" :class="{ 'agent-card--high-risk': agent.risk_level === 'high' }" shadow="never">
    <div class="agent-card__body">
      <div class="agent-card__header">
        <div class="agent-card__title-block">
          <h2>{{ agent.name }}</h2>
          <p>{{ agent.description || '暂无说明' }}</p>
        </div>
        <el-tag :type="riskTagType(agent.risk_level)" effect="plain">
          {{ agent.risk_level }}
        </el-tag>
      </div>

      <div class="agent-card__meta">
        <el-tag effect="plain">{{ agent.category || '未分类' }}</el-tag>
        <span>{{ agent.openclaw_agent_id }}</span>
      </div>

      <div class="agent-card__capabilities">
        <el-tag :type="agent.support_files ? 'success' : 'info'" plain>
          <el-icon><Files /></el-icon>
          文件{{ agent.support_files ? '支持' : '不支持' }}
        </el-tag>
        <el-tag :type="agent.support_images ? 'success' : 'info'" plain>
          <el-icon><Picture /></el-icon>
          图片{{ agent.support_images ? '支持' : '不支持' }}
        </el-tag>
      </div>

      <el-alert
        v-if="agent.risk_level === 'high'"
        class="risk-alert"
        title="高风险 Agent，进入对话前需要确认。"
        type="error"
        :closable="false"
        show-icon
      />

      <div class="agent-card__actions">
        <el-button type="primary" :icon="ChatDotRound" @click="$emit('open-chat', agent)">
          进入对话
        </el-button>
      </div>
    </div>
  </el-card>
</template>

<style scoped>
.agent-card {
  height: 100%;
  border-radius: 8px;
}

.agent-card--high-risk {
  border-color: #f56c6c;
}

.agent-card__body {
  display: grid;
  min-height: 236px;
  gap: 16px;
}

.agent-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.agent-card__title-block {
  min-width: 0;
}

h2,
p {
  margin: 0;
}

h2 {
  font-size: 18px;
  line-height: 1.35;
}

p {
  margin-top: 8px;
  color: #6f7785;
  line-height: 1.55;
}

.agent-card__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  color: #6f7785;
  font-size: 13px;
}

.agent-card__meta span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-card__capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.risk-alert {
  margin: 0;
}

.agent-card__actions {
  display: flex;
  justify-content: flex-end;
  align-self: end;
}
</style>
