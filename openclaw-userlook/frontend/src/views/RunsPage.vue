<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Download, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { downloadFile, formatFileSize } from '../api/files'
import { fetchRuns, type TaskRun } from '../api/runs'

const router = useRouter()
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
  <main class="runs-page">
    <section class="page-shell">
      <header class="header-row">
        <div>
          <h1>任务中心</h1>
          <p>查看对话触发的 TaskRun 运行记录和输出文件</p>
        </div>
        <div class="header-actions">
          <el-button :icon="Refresh" :loading="loading" @click="loadRuns">刷新</el-button>
          <el-button @click="router.push({ name: 'dashboard' })">返回首页</el-button>
        </div>
      </header>

      <el-table v-loading="loading" :data="runs" row-key="id" border>
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
              <div v-if="row.output_files.length" class="output-files">
                <strong>输出文件</strong>
                <el-button
                  v-for="file in row.output_files"
                  :key="file.id"
                  link
                  type="primary"
                  :icon="Download"
                  @click="downloadFile(file)"
                >
                  {{ file.original_name }} ({{ formatFileSize(file.file_size) }})
                </el-button>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="Run ID" width="100" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Agent" min-width="180">
          <template #default="{ row }">
            {{ row.agent_name || row.agent_code || row.agent_id }}
          </template>
        </el-table-column>
        <el-table-column prop="conversation_id" label="会话" width="110" />
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
        <el-table-column prop="finished_at" label="完成时间" min-width="180" />
      </el-table>
    </section>
  </main>
</template>

<style scoped>
.runs-page {
  min-height: 100vh;
  background: #f5f7fb;
  color: #1f2937;
}

.page-shell {
  width: min(1180px, calc(100% - 32px));
  margin: 0 auto;
  padding: 40px 0;
}

.header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 20px;
}

.header-actions,
.output-files {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1.25;
}

p {
  margin: 8px 0 0;
  color: #667085;
}

.run-detail {
  display: grid;
  gap: 14px;
  padding: 8px 24px;
}

pre {
  margin: 8px 0 0;
  padding: 10px 12px;
  border: 1px solid #d9e2ec;
  border-radius: 6px;
  background: #f8fafc;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

@media (max-width: 720px) {
  .page-shell {
    width: min(100% - 24px, 1180px);
    padding: 24px 0;
  }

  .header-row {
    flex-direction: column;
  }
}
</style>
