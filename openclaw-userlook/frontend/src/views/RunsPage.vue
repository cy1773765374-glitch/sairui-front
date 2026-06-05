<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Delete, Download, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { fetchAgents, type Agent } from '../api/agents'
import { downloadFile, formatFileSize } from '../api/files'
import {
  batchDeleteRuns,
  deleteRun,
  fetchRuns,
  isTerminalRunStatus,
  type TaskRun,
  type TaskRunStatus,
} from '../api/runs'
import BatchDeleteToolbar from '../components/BatchDeleteToolbar.vue'
import { useAuthStore } from '../stores/auth'
import { elapsedBetween, formatDateTimeShanghai, parseBackendTime } from '../utils/time'

const authStore = useAuthStore()
const loading = ref(false)
const deleting = ref(false)
const runs = ref<TaskRun[]>([])
const agents = ref<Agent[]>([])
const selectedRuns = ref<TaskRun[]>([])
const tableRef = ref()
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
const hiddenRunStorageKey = computed(
  () => `openclaw_userlook_hidden_task_runs:${authStore.user?.id ?? authStore.user?.username ?? 'anonymous'}`,
)
const hiddenRunIds = ref<number[]>([])
const visibleRuns = computed(() => {
  if (authStore.isAdmin) {
    return runs.value
  }
  const hidden = new Set(hiddenRunIds.value)
  return runs.value.filter((run) => !hidden.has(run.id))
})

function loadHiddenRunIds() {
  if (authStore.isAdmin) {
    hiddenRunIds.value = []
    return
  }
  try {
    const rawValue = localStorage.getItem(hiddenRunStorageKey.value)
    const parsed = rawValue ? JSON.parse(rawValue) : []
    hiddenRunIds.value = Array.isArray(parsed)
      ? parsed.map((item) => Number(item)).filter((item) => Number.isInteger(item) && item > 0)
      : []
  } catch {
    hiddenRunIds.value = []
  }
}

function persistHiddenRunIds() {
  localStorage.setItem(hiddenRunStorageKey.value, JSON.stringify(Array.from(new Set(hiddenRunIds.value))))
}

function hideRunsLocally(runIds: number[]) {
  hiddenRunIds.value = Array.from(new Set([...hiddenRunIds.value, ...runIds]))
  persistHiddenRunIds()
  selectedRuns.value = selectedRuns.value.filter((run) => !hiddenRunIds.value.includes(run.id))
}

async function loadRuns() {
  loading.value = true
  try {
    loadHiddenRunIds()
    runs.value = await fetchRuns({
      status: filters.value.status || undefined,
      agent_id: filters.value.agent_id,
      run_type: filters.value.run_type || undefined,
      active_only: filters.value.active_only,
    })
    selectedRuns.value = []
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
  if (status === 'running' || status === 'queued' || status === 'pending') {
    return 'warning'
  }
  return 'info'
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

function queueDuration(row: TaskRun) {
  return elapsedBetween(row.queued_at || row.created_at, row.started_at)
}

function runDuration(row: TaskRun) {
  return elapsedBetween(row.started_at, row.finished_at)
}

function rawPayloadObject(row: TaskRun): Record<string, unknown> {
  return row.raw_payload && typeof row.raw_payload === 'object' && !Array.isArray(row.raw_payload)
    ? (row.raw_payload as Record<string, unknown>)
    : {}
}

function runnerLabel(row: TaskRun) {
  if (row.runner_name === 'ppt_generation_job') {
    return 'PPT 本地生成'
  }
  if (row.runner_name === 'daoban_job') {
    return '刀版本地生成'
  }
  if (row.runner_name === 'gateway_chat') {
    return 'Gateway 对话'
  }
  return row.runner_name || row.task_kind || '-'
}

function runOutputPath(row: TaskRun) {
  const rawPayload = rawPayloadObject(row)
  return String(
    rawPayload.windows_path ||
      rawPayload.pptx_path ||
      rawPayload.run_dir ||
      row.output_dir ||
      row.output_text ||
      '-',
  )
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

function onSelectionChange(rows: TaskRun[]) {
  selectedRuns.value = rows
}

function clearSelection() {
  tableRef.value?.clearSelection()
  selectedRuns.value = []
}

async function confirmDeleteRun(row: TaskRun) {
  if (!isTerminalRunStatus(row.status)) {
    ElMessage.warning('运行中任务不能删除，请先取消或等待结束')
    return
  }
  if (!authStore.isAdmin) {
    try {
      await ElMessageBox.confirm('仅从当前列表隐藏，不会删除任务记录。', '从列表移除', {
        confirmButtonText: '从列表移除',
        cancelButtonText: '取消',
        type: 'warning',
      })
    } catch {
      return
    }
    hideRunsLocally([row.id])
    ElMessage.success('任务已从当前列表移除')
    return
  }

  try {
    await ElMessageBox.confirm('将删除数据库任务记录，此操作不可恢复。', '删除记录', {
      confirmButtonText: '删除记录',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }

  deleting.value = true
  try {
    await deleteRun(row.id)
    ElMessage.success('任务已删除')
    await loadRuns()
  } catch {
    ElMessage.error('任务删除失败')
  } finally {
    deleting.value = false
  }
}

async function confirmBatchDelete() {
  if (selectedRuns.value.some((run) => !isTerminalRunStatus(run.status))) {
    ElMessage.warning('运行中任务不能删除，请先取消或等待结束')
    return
  }
  if (!authStore.isAdmin) {
    try {
      await ElMessageBox.confirm(
        `仅从当前列表隐藏选中的 ${selectedRuns.value.length} 个任务，不会删除任务记录。`,
        '从列表移除',
        {
          confirmButtonText: '从列表移除',
          cancelButtonText: '取消',
          type: 'warning',
        },
      )
    } catch {
      return
    }
    hideRunsLocally(selectedRuns.value.map((run) => run.id))
    clearSelection()
    ElMessage.success('任务已从当前列表移除')
    return
  }

  try {
    await ElMessageBox.confirm(`将删除选中的 ${selectedRuns.value.length} 个数据库任务记录，此操作不可恢复。`, '批量删除记录', {
      confirmButtonText: '删除记录',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }

  deleting.value = true
  try {
    const result = await batchDeleteRuns(selectedRuns.value.map((run) => run.id))
    if (result.skipped.length > 0) {
      ElMessage.warning(`已删除 ${result.deleted_ids.length} 个任务，跳过 ${result.skipped.length} 个`)
    } else {
      ElMessage.success(`已删除 ${result.deleted_ids.length} 个任务`)
    }
    await loadRuns()
  } catch {
    ElMessage.error('批量删除任务失败')
  } finally {
    deleting.value = false
  }
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

      <BatchDeleteToolbar
        :selected-count="selectedRuns.length"
        :loading="deleting"
        :action-label="authStore.isAdmin ? '批量删除记录' : '批量从列表移除'"
        @delete-selected="confirmBatchDelete"
        @clear-selection="clearSelection"
      />

      <el-table
        ref="tableRef"
        v-loading="loading"
        :data="visibleRuns"
        row-key="id"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="48" />
        <el-table-column type="expand">
          <template #default="{ row }: { row: TaskRun }">
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
          <template #default="{ row }: { row: TaskRun }">
            <el-tag :type="statusType(row.status)" effect="plain">{{ row.status }}</el-tag>
            <el-tag v-if="isRunWarning(row)" class="warning-tag" type="danger" effect="plain">
              heartbeat 过旧
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="run_type" label="run_type" width="110" />
        <el-table-column label="任务类型" min-width="140">
          <template #default="{ row }: { row: TaskRun }">
            {{ runnerLabel(row) }}
          </template>
        </el-table-column>
        <el-table-column prop="task_kind" label="task_kind" width="120" />
        <el-table-column prop="priority" label="priority" width="100" />
        <el-table-column label="agent" min-width="170">
          <template #default="{ row }: { row: TaskRun }">
            {{ row.agent_name || row.agent_code || row.agent_id }}
          </template>
        </el-table-column>
        <el-table-column label="输出路径" min-width="260">
          <template #default="{ row }: { row: TaskRun }">
            <span class="path-cell">{{ runOutputPath(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="workspace" min-width="260">
          <template #default="{ row }: { row: TaskRun }">
            <span class="path-cell">{{ row.workspace_path || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="created_at" min-width="180">
          <template #default="{ row }: { row: TaskRun }">{{ formatDateTimeShanghai(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="queued_at" min-width="180">
          <template #default="{ row }: { row: TaskRun }">{{ formatDateTimeShanghai(row.queued_at) }}</template>
        </el-table-column>
        <el-table-column label="started_at" min-width="180">
          <template #default="{ row }: { row: TaskRun }">{{ formatDateTimeShanghai(row.started_at) }}</template>
        </el-table-column>
        <el-table-column label="排队耗时" width="110">
          <template #default="{ row }: { row: TaskRun }">
            {{ queueDuration(row) }}
          </template>
        </el-table-column>
        <el-table-column label="执行耗时" width="110">
          <template #default="{ row }: { row: TaskRun }">
            {{ runDuration(row) }}
          </template>
        </el-table-column>
        <el-table-column label="heartbeat_at" min-width="180">
          <template #default="{ row }: { row: TaskRun }">{{ formatDateTimeShanghai(row.heartbeat_at) }}</template>
        </el-table-column>
        <el-table-column label="finished_at" min-width="180">
          <template #default="{ row }: { row: TaskRun }">{{ formatDateTimeShanghai(row.finished_at) }}</template>
        </el-table-column>
        <el-table-column prop="timeout_seconds" label="timeout" width="100" />
        <el-table-column label="cancel" width="96">
          <template #default="{ row }: { row: TaskRun }">
            <el-tag :type="row.cancel_requested ? 'warning' : 'info'" effect="plain">
              {{ row.cancel_requested ? 'yes' : 'no' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="output_files" min-width="220">
          <template #default="{ row }: { row: TaskRun }">
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
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }: { row: TaskRun }">
            <el-tooltip :content="isTerminalRunStatus(row.status) ? (authStore.isAdmin ? '删除数据库任务记录' : '仅从当前列表隐藏') : '运行中任务不能删除'">
              <span>
                <el-button
                  link
                  type="danger"
                  :icon="Delete"
                  :disabled="!isTerminalRunStatus(row.status)"
                  @click="confirmDeleteRun(row)"
                >
                  {{ authStore.isAdmin ? '删除记录' : '从列表移除' }}
                </el-button>
              </span>
            </el-tooltip>
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

.path-cell {
  display: inline-block;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  white-space: nowrap;
}

@media (max-width: 720px) {
  .page-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
