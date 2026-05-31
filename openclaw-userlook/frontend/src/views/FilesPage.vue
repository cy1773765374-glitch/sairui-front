<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Download, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { downloadFile, fetchFiles, formatFileSize, type UserFile } from '../api/files'

const router = useRouter()
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
  <main class="files-page">
    <section class="page-shell">
      <header class="header-row">
        <div>
          <h1>文件中心</h1>
          <p>查看已上传文件和 Agent 输出文件</p>
        </div>
        <div class="header-actions">
          <el-button :icon="Refresh" :loading="loading" @click="loadFiles">刷新</el-button>
          <el-button @click="router.push({ name: 'dashboard' })">返回首页</el-button>
        </div>
      </header>

      <el-table v-loading="loading" :data="files" border>
        <el-table-column prop="id" label="ID" width="90" />
        <el-table-column label="文件名" min-width="240">
          <template #default="{ row }">
            <span class="file-name">{{ row.original_name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="用途" width="100">
          <template #default="{ row }">
            <el-tag :type="row.purpose === 'output' ? 'success' : 'info'" effect="plain">
              {{ purposeLabel(row.purpose) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="file_type" label="类型" width="100" />
        <el-table-column label="大小" width="120">
          <template #default="{ row }">{{ formatFileSize(row.file_size) }}</template>
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
    </section>
  </main>
</template>

<style scoped>
.files-page {
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

.header-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
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

.file-name {
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

  .header-actions {
    justify-content: flex-start;
  }
}
</style>
