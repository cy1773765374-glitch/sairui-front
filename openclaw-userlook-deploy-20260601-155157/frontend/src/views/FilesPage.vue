<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Download, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { downloadFile, fetchFiles, formatFileSize, type UserFile } from '../api/files'

const loading = ref(false)
const files = ref<UserFile[]>([])

async function loadFiles() {
  loading.value = true
  try {
    files.value = await fetchFiles()
  } catch {
    ElMessage.error('文件列表加载失败')
  } finally {
    loading.value = false
  }
}

function purposeLabel(purpose: UserFile['purpose']) {
  if (purpose === 'upload') {
    return '上传'
  }
  if (purpose === 'output') {
    return '输出'
  }
  return '临时'
}

onMounted(loadFiles)
</script>

<template>
  <section class="files-page page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">Files</p>
        <h1>文件中心</h1>
        <p>查看已上传文件和 Agent 输出文件。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadFiles">刷新</el-button>
    </header>

    <el-card class="table-card" shadow="never">
      <el-table v-loading="loading" :data="files">
        <el-table-column label="文件名" min-width="260">
          <template #default="{ row }">
            <span class="file-name">{{ row.original_name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="file_type" label="类型" width="120" />
        <el-table-column label="大小" width="120">
          <template #default="{ row }">{{ formatFileSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="purpose" width="120">
          <template #default="{ row }">
            <el-tag :type="row.purpose === 'output' ? 'success' : 'info'" effect="plain">
              {{ purposeLabel(row.purpose) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="Download" @click="downloadFile(row)">
              下载
            </el-button>
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

.file-name {
  overflow-wrap: anywhere;
}

@media (max-width: 720px) {
  .page-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
