<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Delete, Download, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  batchDeleteFiles,
  deleteFile,
  downloadFile,
  fetchFiles,
  formatFileSize,
  type UserFile,
} from '../api/files'
import BatchDeleteToolbar from '../components/BatchDeleteToolbar.vue'
import { formatDateTimeShanghai } from '../utils/time'

const loading = ref(false)
const deleting = ref(false)
const files = ref<UserFile[]>([])
const selectedFiles = ref<UserFile[]>([])
const tableRef = ref()

async function loadFiles() {
  loading.value = true
  try {
    files.value = await fetchFiles()
    selectedFiles.value = []
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

function onSelectionChange(rows: UserFile[]) {
  selectedFiles.value = rows
}

function clearSelection() {
  tableRef.value?.clearSelection()
  selectedFiles.value = []
}

async function confirmDeleteFile(row: UserFile) {
  try {
    await ElMessageBox.confirm('确认删除该文件？', '删除文件', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }

  deleting.value = true
  try {
    await deleteFile(row.id)
    ElMessage.success('文件已删除')
    await loadFiles()
  } catch {
    ElMessage.error('文件删除失败')
  } finally {
    deleting.value = false
  }
}

async function confirmBatchDelete() {
  try {
    await ElMessageBox.confirm(`确认删除选中的 ${selectedFiles.value.length} 个文件？`, '批量删除文件', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }

  deleting.value = true
  try {
    const result = await batchDeleteFiles(selectedFiles.value.map((file) => file.id))
    if (result.skipped.length > 0) {
      ElMessage.warning(`已删除 ${result.deleted_ids.length} 个文件，跳过 ${result.skipped.length} 个`)
    } else {
      ElMessage.success(`已删除 ${result.deleted_ids.length} 个文件`)
    }
    await loadFiles()
  } catch {
    ElMessage.error('批量删除文件失败')
  } finally {
    deleting.value = false
  }
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
      <BatchDeleteToolbar
        :selected-count="selectedFiles.length"
        :loading="deleting"
        @delete-selected="confirmBatchDelete"
        @clear-selection="clearSelection"
      />

      <el-table ref="tableRef" v-loading="loading" :data="files" row-key="id" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="48" />
        <el-table-column label="文件名" min-width="260">
          <template #default="{ row }: { row: UserFile }">
            <span class="file-name">{{ row.original_name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="file_type" label="类型" width="120" />
        <el-table-column label="大小" width="120">
          <template #default="{ row }: { row: UserFile }">{{ formatFileSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="purpose" width="120">
          <template #default="{ row }: { row: UserFile }">
            <el-tag :type="row.purpose === 'output' ? 'success' : 'info'" effect="plain">
              {{ purposeLabel(row.purpose) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="180">
          <template #default="{ row }: { row: UserFile }">{{ formatDateTimeShanghai(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }: { row: UserFile }">
            <el-button link type="primary" :icon="Download" @click="downloadFile(row)">
              下载
            </el-button>
            <el-button link type="danger" :icon="Delete" @click="confirmDeleteFile(row)">
              删除
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
