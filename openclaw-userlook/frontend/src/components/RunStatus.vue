<script setup lang="ts">
import { computed } from 'vue'
import { Download } from '@element-plus/icons-vue'

import { downloadFile, formatFileSize, type UserFile } from '../api/files'
import type { TaskRunStatus } from '../api/runs'

const props = defineProps<{
  runId: number | null
  status: TaskRunStatus | ''
  message?: string
  outputFiles: UserFile[]
}>()

const tagType = computed(() => {
  if (props.status === 'success') {
    return 'success'
  }
  if (props.status === 'failed' || props.status === 'timeout' || props.status === 'stale') {
    return 'danger'
  }
  if (props.status === 'running') {
    return 'warning'
  }
  return 'info'
})

const statusLabel = computed(() => {
  if (props.status === 'pending' || props.status === 'queued' || props.status === 'running') {
    return '执行中'
  }
  if (props.status === 'success') {
    return '完成'
  }
  if (props.status === 'failed') {
    return '失败'
  }
  if (props.status === 'timeout') {
    return '超时'
  }
  if (props.status === 'stale') {
    return '异常中断'
  }
  if (props.status === 'cancelled') {
    return '已取消'
  }
  return 'idle'
})
</script>

<template>
  <section v-if="runId || status || outputFiles.length" class="run-status">
    <div class="status-line">
      <el-tag :type="tagType" effect="plain">
        {{ runId ? `Run #${runId}` : 'Run' }} {{ statusLabel }}
      </el-tag>
      <span v-if="message" class="status-message">{{ message }}</span>
    </div>
    <div v-if="outputFiles.length" class="output-files">
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
  </section>
</template>

<style scoped>
.run-status {
  display: grid;
  gap: 8px;
  padding: 10px 20px;
  border-bottom: 1px solid #d9e2ec;
  background: #ffffff;
}

.status-line,
.output-files {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.status-message {
  color: #667085;
  font-size: 13px;
}
</style>
