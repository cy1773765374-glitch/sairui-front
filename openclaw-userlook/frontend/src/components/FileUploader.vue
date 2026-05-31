<script setup lang="ts">
import { Upload } from '@element-plus/icons-vue'
import { ElMessage, type UploadRequestOptions } from 'element-plus'

import { formatFileSize, uploadFile, type UserFile } from '../api/files'

const emit = defineEmits<{
  uploaded: [file: UserFile]
}>()

const allowedExtensions = '.txt,.md,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.pdf,.png,.jpg,.jpeg'

async function uploadWithApi(options: UploadRequestOptions) {
  try {
    const response = await uploadFile(options.file)
    emit('uploaded', response.file)
    ElMessage.success(`已上传 ${response.file.original_name} (${formatFileSize(response.file.file_size)})`)
    options.onSuccess(response)
  } catch (error) {
    ElMessage.error('文件上传失败')
    options.onError(error as Parameters<UploadRequestOptions['onError']>[0])
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
