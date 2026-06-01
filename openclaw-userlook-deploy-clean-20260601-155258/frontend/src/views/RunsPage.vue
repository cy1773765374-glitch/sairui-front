<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Download, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { downloadFile, formatFileSize } from '../api/files'
import { fetchRuns, type TaskRun } from '../api/runs'

const loading = ref(false)
const runs = ref<TaskRun[]>([])

async function loadRuns() {
  loading.value = true
  try {
    runs.value = await fetchRuns()
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
  if (status === 'failed' || status === 'cancelled') {
    return 'danger'
  }
  if (status === 'running') {
    return 'warning'
  }
  return 'info'
}

onMounted(loadRuns)
</script>

<template>
  <section class="runs-page page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">Runs</p>
        <h1>任务中心</h1>
        <p>查看对话触发的 task_run 记录、运行状态和输出文件。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadRuns">刷新</el-button>
    </header>

    <el-card class="table-card" shadow="never">
      <el-table v-loading="loading" :data="runs" row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="run-detail">
              <div>
                <strong>输入</strong>
                <pre>{{ row.input_text }}</pre>
              </div>
              <div v-if="row.output_text">
                <strong>输出</strong>
                <pre>{{ row.output_text }}</pre>
              </div>
              <div v-if="row.error_message">
                <strong>错误</strong>
                <pre>{{ row.error_message }}</pre>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="Run ID" width="96" />
        <el-table-column label="status" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="agent" min-width="170">
          <template #default="{ row }">
            {{ row.agent_name || row.agent_code || row.agent_id }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="created_at" min-width="180" />
        <el-table-column prop="started_at" label="started_at" min-width="180" />
        <el-table-column prop="finished_at" label="finished_at" min-width="180" />
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

.page-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
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
