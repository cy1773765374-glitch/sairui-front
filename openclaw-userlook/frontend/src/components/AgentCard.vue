<script setup lang="ts">
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
  <article class="agent-card" :class="{ 'agent-card--high-risk': agent.risk_level === 'high' }">
    <div class="agent-card__header">
      <div class="agent-card__title-block">
        <h2>{{ agent.name }}</h2>
        <p>{{ agent.description || '暂无描述' }}</p>
      </div>
      <el-tag :type="riskTagType(agent.risk_level)" effect="dark">
        {{ agent.risk_level }}
      </el-tag>
    </div>

    <el-alert
      v-if="agent.risk_level === 'high'"
      class="risk-alert"
      title="高风险 Agent，请确认授权范围和使用场景。"
      type="error"
      :closable="false"
      show-icon
    />

    <div class="agent-card__meta">
      <span>分类：{{ agent.category || '未分类' }}</span>
      <span>OpenClaw：{{ agent.openclaw_agent_id }}</span>
    </div>

    <div class="agent-card__capabilities">
      <el-tag :type="agent.support_files ? 'success' : 'info'" plain>
        文件：{{ agent.support_files ? '支持' : '不支持' }}
      </el-tag>
      <el-tag :type="agent.support_images ? 'success' : 'info'" plain>
        图片：{{ agent.support_images ? '支持' : '不支持' }}
      </el-tag>
    </div>

    <div class="agent-card__actions">
      <el-button type="primary" @click="$emit('open-chat', agent)">进入对话</el-button>
    </div>
  </article>
</template>

<style scoped>
.agent-card {
  min-height: 220px;
  padding: 20px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #ffffff;
  color: #1f2937;
}

.agent-card--high-risk {
  border-color: #f56c6c;
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

h2 {
  margin: 0;
  font-size: 18px;
  line-height: 1.35;
}

p {
  margin: 8px 0 0;
  color: #667085;
  line-height: 1.55;
}

.risk-alert {
  margin-top: 16px;
}

.agent-card__meta {
  display: grid;
  gap: 8px;
  margin-top: 18px;
  color: #475467;
  font-size: 14px;
}

.agent-card__capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.agent-card__actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
}
</style>
