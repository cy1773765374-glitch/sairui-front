<script setup lang="ts">
import { Delete, Close } from '@element-plus/icons-vue'

defineProps<{
  selectedCount: number
  loading?: boolean
  actionLabel?: string
}>()

defineEmits<{
  deleteSelected: []
  clearSelection: []
}>()
</script>

<template>
  <div class="batch-delete-toolbar" :class="{ 'batch-delete-toolbar--active': selectedCount > 0 }">
    <span>{{ selectedCount > 0 ? `已选择 ${selectedCount} 项` : '未选择项目' }}</span>
    <div class="batch-delete-toolbar__actions">
      <el-button :icon="Close" :disabled="selectedCount === 0 || loading" @click="$emit('clearSelection')">
        清空选择
      </el-button>
      <el-button
        type="danger"
        :icon="Delete"
        :loading="loading"
        :disabled="selectedCount === 0"
        @click="$emit('deleteSelected')"
      >
        {{ actionLabel || '批量删除' }}
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.batch-delete-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  padding: 10px 12px;
  border: 1px solid #dfe5ee;
  border-radius: 8px;
  background: #f8fafc;
  color: #667085;
}

.batch-delete-toolbar--active {
  border-color: #f3c7c7;
  background: #fff7f7;
  color: #3c4043;
}

.batch-delete-toolbar__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 640px) {
  .batch-delete-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
