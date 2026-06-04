<script setup lang="ts">
import { ref } from 'vue'
import { Upload } from '@element-plus/icons-vue'
import { ElMessage, type UploadRequestOptions } from 'element-plus'
import axios from 'axios'

import { formatFileSize, uploadFile, type UserFile } from '../api/files'

const emit = defineEmits<{
  uploaded: [file: UserFile]
  uploadingChange: [uploading: boolean]
}>()

const activeUploadCount = ref(0)

const allowedExtensions = [
  '.txt',
  '.text',
  '.md',
  '.markdown',
  '.csv',
  '.tsv',
  '.json',
  '.jsonl',
  '.yaml',
  '.yml',
  '.xml',
  '.html',
  '.htm',
  '.log',
  '.rtf',
  '.doc',
  '.docx',
  '.odt',
  '.xls',
  '.xlsx',
  '.ods',
  '.ppt',
  '.pptx',
  '.odp',
  '.pdf',
  '.zip',
  '.rar',
  '.7z',
  '.tar',
  '.gz',
  '.png',
  '.jpg',
  '.jpeg',
  '.gif',
  '.webp',
  '.bmp',
  '.tif',
  '.tiff',
  '.svg',
  '.heic',
  '.heif',
].join(',')

async function uploadWithApi(options: UploadRequestOptions) {
  activeUploadCount.value += 1
  emit('uploadingChange', true)
  try {
    const response = await uploadFile(options.file)
    const realId = response.file?.id ?? response.file_id ?? response.id
    if (!realId) {
      throw new Error('missing uploaded file id')
    }
    const uploadedFile: UserFile = {
      ...response.file,
      id: Number(realId),
      mime_type: response.file?.mime_type ?? options.file.type ?? null,
    }
    emit('uploaded', uploadedFile)
    ElMessage.success(`已上传 ${uploadedFile.original_name} (${formatFileSize(uploadedFile.file_size)})`)
    options.onSuccess(response)
  } catch (error) {
    const detail = axios.isAxiosError(error) ? error.response?.data?.detail : ''
    ElMessage.error(detail ? `文件上传失败：${detail}` : '文件上传失败')
    options.onError(error as Parameters<UploadRequestOptions['onError']>[0])
  } finally {
    activeUploadCount.value = Math.max(0, activeUploadCount.value - 1)
    emit('uploadingChange', activeUploadCount.value > 0)
  }
}
</script>

<template>
  <el-upload
    class="file-uploader"
    action="#"
    :accept="allowedExtensions"
    :auto-upload="true"
    :http-request="uploadWithApi"
    :show-file-list="false"
  >
    <el-button :icon="Upload">上传文件</el-button>
  </el-upload>
</template>

<style scoped>
.file-uploader {
  display: inline-flex;
}
</style>
