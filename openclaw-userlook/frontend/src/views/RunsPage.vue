<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Download, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchAgents, type Agent } from '../api/agents'
import { downloadFile, formatFileSize } from '../api/files'
import { fetchRuns, type TaskRun, type TaskRunStatus } from '../api/runs'

const loading = ref(false)
const runs = ref<TaskRun[]>([])
const agents = ref<Agent[]>([])
const filters = ref<{
  status: TaskRunStatus | ''
  agent_id: number | undefined
  run_type: string
  active_only: boolean
}>({
  status: '',
  agent_id: undefined,
  run_type: '',
  active_only: false,
})

const statusOptions: Array<TaskRunStatus> = [
  'pending',
  'queued',
  'running',
  'success',
  'failed',
  'cancelled',
  'timeout',
  'stale',
]

const hasFilters = computed(
  () => Boolean(filters.value.status || filters.value.agent_id || filters.value.run_type || filters.value.active_only),
)

async function loadRuns() {
  loading.value = true
  try {
    runs.value = await fetchRuns({
      status: filters.value.status || undefined,
      agent_id: filters.value.agent_id,
      run_type: filters.value.run_type || undefined,
      active_only: filters.value.active_only,
    })
  } catch {
    ElMessage.error('任务列表加载失败')
  } finally {
    loading.value = false
  }
}

function statusType(status: TaskRun['status']) {
  if (status === 'success') {
    return 'success'
  }
  if (status === 'failed' || status === 'timeout' || status === 'stale') {
    return 'danger'
  }
  if (status === 'running') {
    return 'warning'
  }
  return 'info'
}

function parseBackendTime(value: string | null | undefined) {
  if (!value) {
    return null
  }
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value)
  const timestamp = Date.parse(hasTimezone ? value : `${value}Z`)
  return Number.isNaN(timestamp) ? null : timestamp
}

function isRunWarning(row: TaskRun) {
  if (row.status !== 'running') {
    return false
  }
  const heartbeat = parseBackendTime(row.heartbeat_at || row.started_at)
  if (heartbeat === null) {
    return false
  }
  return Date.now() - heartbeat > 5 * 60 * 1000
}

function formatDurationMs(ms: number | null) {
  if (ms === null || ms < 0) {
    return '-'
  }
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) {
    return `${seconds}s`
  }
  const minutes = Math.floor(seconds / 60)
  const restSeconds = seconds % 60
  if (minutes < 60) {
    return `${minutes}m ${restSeconds}s`
  }
  const hours = Math.floor(minutes / 60)
  const restMinutes = minutes % 60
  return `${hours}h ${restMinutes}m`
}

function elapsedBetween(start: string | null | undefined, end: string | null | undefined) {
  const startTime = parseBackendTime(start)
  const endTime = parseBackendTime(end)
  if (startTime === null || endTime === null) {
    return '-'
  }
  return formatDurationMs(endTime - startTime)
}

function queueDuration(row: TaskRun) {
  return elapsedBetween(row.queued_at || row.created_at, row.started_at)
}

function runDuration(row: TaskRun) {
  return elapsedBetween(row.started_at, row.finished_at)
}

function resetFilters() {
  filters.value = {
    status: '',
    agent_id: undefined,
    run_type: '',
    active_only: false,
  }
  void loadRuns()
}

onMounted(async () => {
  try {
    agents.value = await fetchAgents()
  } catch {
    agents.value = []
  }
  await loadRuns()
})
</script>

<template>
  <section class="runs-page page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">Runs</p>
        <h1>任务中心</h1>
        <p>查看对话触发的 task_run 记录、运行状态和输出文件。</p>
      </div>
      <div class="heading-actions">
        <el-button v-if="hasFilters" plain @click="resetFilters">重置筛选</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="loadRuns">刷新</el-button>
      </div>
    </header>

    <el-card class="table-card" shadow="never">
      <div class="run-filters">
        <el-select v-model="filters.status" clearable placeholder="status" @change="loadRuns">
          <el-option v-for="status in statusOptions" :key="status" :label="status" :value="status" />
        </el-select>
        <el-select v-model="filters.agent_id" clearable filterable placeholder="agent" @change="loadRuns">
          <el-option
            v-for="agent in agents"
            :key="agent.id"
            :label="agent.name"
            :value="agent.id"
          />
        </el-select>
        <el-select v-model="filters.run_type" clearable placeholder="run_type" @change="loadRuns">
          <el-option label="chat" value="chat" />
          <el-option label="job" value="job" />
          <el-option label="system" value="system" />
        </el-select>
        <el-checkbox v-model="filters.active_only" @change="loadRuns">仅 active</el-checkbox>
      </div>
      <el-table v-loading="loading" :data="runs" row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="run-detail">
              <div>
                <strong>输入</strong>
                <pre>{{ row.input_text }}</pre>
              </div>
              <div>
                <strong>输出</strong>
                <pre>{{ row.output_text || '-' }}</pre>
              </div>
              <div v-if="row.error_message">
                <strong>错误</strong>
                <pre>{{ row.error_message }}</pre>
              </div>
              <div>
                <strong>run raw_payload 轻量摘要</strong>
                <pre>{{ row.raw_payload ? JSON.stringify(row.raw_payload, null, 2) : '-' }}</pre>
              </div>
              <div v-if="row.raw_payload_summary">
                <strong>raw_payload 摘要</strong>
                <pre>{{ JSON.stringify(row.raw_payload_summary, null, 2) }}</pre>
              </div>
              <div>
                <strong>输出文件快照</strong>
                <pre>{{ row.output_files_json ? JSON.stringify(row.output_files_json, null, 2) : '-' }}</pre>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="Run ID" width="96" />
        <el-table-column label="status" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">{{ row.status }}</el-tag>
            <el-tag v-if="isRunWarning(row)" class="warning-tag" type="danger" effect="plain">
              heartbeat 过旧
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="run_type" label="run_type" width="110" />
        <el-table-column prop="priority" label="priority" width="100" />
        <el-table-column label="agent" min-width="170">
          <template #default="{ row }">
            {{ row.agent_name || row.agent_code || row.agent_id }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="created_at" min-width="180" />
        <el-table-column prop="queued_at" label="queued_at" min-width="180" />
        <el-table-column prop="started_at" label="started_at" min-width="180" />
        <el-table-column label="排队耗时" width="110">
          <template #default="{ row }">
            {{ queueDuration(row) }}
          </template>
        </el-table-column>
        <el-table-column label="执行耗时" width="110">
          <template #default="{ row }">
            {{ runDuration(row) }}
          </template>
        </el-table-column>
        <el-table-column prop="heartbeat_at" label="heartbeat_at" min-width="180" />
        <el-table-column prop="finished_at" label="finished_at" min-width="180" />
        <el-table-column prop="timeout_seconds" label="timeout" width="100" />
        <el-table-column label="cancel" width="96">
          <template #default="{ row }">
            <el-tag :type="row.cancel_requested ? 'warning' : 'info'" effect="plain">
              {{ row.cancel_requested ? 'yes' : 'no' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="output_files" min-width="220">
          <template #default="{ row }">
            <div class="output-files">
              <el-button
                v-for="file in row.output_files"
                :key="file.id"
                link
                type="primary"
                :icon="Download"
                @click="downloadFile(file)"
              >
                {{ file.original_name }} · {{ formatFileSize(file.file_size) }}
              </el-button>
              <span v-if="row.output_files.length === 0">-</span>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>

<style scoped>
.page-stack {
  display: grid;
  gap: 20px;
}

.page-heading,
.heading-actions {
  display: flex;
  gap: 20px;
}

.page-heading {
  align-items: flex-end;
  justify-content: space-between;
}

.heading-actions {
  align-items: center;
}

.eyebrow {
  margin: 0 0 8px;
  color: #1a73e8;
  font-size: 13px;
  font-weight: 700;
}

h1,
p {
  margin: 0;
}

h1 {
  font-size: 28px;
  line-height: 1.25;
}

.page-heading p:last-child {
  margin-top: 8px;
  color: #6f7785;
}

.table-card {
  border-radius: 8px;
}

.run-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.run-filters .el-select {
  width: 180px;
}

.warning-tag {
  margin-left: 6px;
}

.run-detail {
  display: grid;
  gap: 14px;
  padding: 8px 24px;
}

pre {
  margin: 8px 0 0;
  padding: 10px 12px;
  border: 1px solid #dfe5ee;
  border-radius: 6px;
  background: #f8fafc;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.output-files {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 720px) {
  .page-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
