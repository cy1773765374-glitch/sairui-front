<script setup lang="ts">
import { ref } from 'vue'
import { Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { formatFileSize, uploadFile, type UserFile } from '../api/files'

const emit = defineEmits<{
  uploaded: [file: UserFile]
}>()

const inputRef = ref<HTMLInputElement | null>(null)
const uploading = ref(false)

const allowedExtensions = '.txt,.md,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.pdf,.png,.jpg,.jpeg'

function chooseFile() {
  inputRef.value?.click()
}

async function handleChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) {
    return
  }

  uploading.value = true
  try {
    const response = await uploadFile(file)
    emit('uploaded', response.file)
    ElMessage.success(`已上传 ${response.file.original_name} (${formatFileSize(response.file.file_size)})`)
  } catch {
    ElMessage.error('文件上传失败')
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div class="file-uploader">
    <input
      ref="inputRef"
      class="file-input"
      type="file"
      :accept="allowedExtensions"
      @change="handleChange"
    />
    <el-button :icon="Upload" :loading="uploading" :disabled="uploading" @click="chooseFile">
      上传文件
    </el-button>
  </div>
</template>

<style scoped>
.file-uploader {
  display: inline-flex;
}

.file-input {
  display: none;
}
</style>
