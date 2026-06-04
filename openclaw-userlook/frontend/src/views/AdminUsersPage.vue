<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { approveAdminUser, disableAdminUser, fetchAdminUsers } from '../api/adminUsers'
import type { User, UserStatus } from '../api/auth'
import { useAuthStore } from '../stores/auth'
import { formatDateTimeShanghai } from '../utils/time'

const authStore = useAuthStore()
const loading = ref(false)
const users = ref<User[]>([])
const currentUserId = computed(() => authStore.user?.id)

function statusTagType(status: UserStatus) {
  if (status === 'active') {
    return 'success'
  }
  if (status === 'disabled') {
    return 'danger'
  }
  return 'warning'
}

async function loadUsers() {
  loading.value = true
  try {
    users.value = await fetchAdminUsers()
  } catch {
    ElMessage.error('用户列表加载失败')
  } finally {
    loading.value = false
  }
}

async function approveUser(user: User) {
  try {
    await approveAdminUser(user.id)
    ElMessage.success('已审核通过')
    await loadUsers()
  } catch {
    ElMessage.error('审核失败')
  }
}

async function disableUser(user: User) {
  try {
    await disableAdminUser(user.id)
    ElMessage.success('已禁用账号')
    await loadUsers()
  } catch {
    ElMessage.error('禁用失败')
  }
}

onMounted(loadUsers)
</script>

<template>
  <section class="admin-users-page page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">Admin</p>
        <h1>用户管理</h1>
        <p>审核 pending 用户，或禁用不再允许访问的账号。</p>
      </div>
      <el-button type="primary" :icon="Refresh" :loading="loading" @click="loadUsers">刷新</el-button>
    </header>

    <el-card class="table-card" shadow="never">
      <el-table v-loading="loading" :data="users">
        <el-table-column prop="username" label="用户名" min-width="140" />
        <el-table-column prop="display_name" label="显示名" min-width="140" />
        <el-table-column label="角色" width="110">
          <template #default="{ row }: { row: User }">
            <el-tag :type="row.role === 'admin' ? 'warning' : 'info'" effect="plain">{{ row.role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }: { row: User }">
            <el-tag :type="statusTagType(row.status)" effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="注册时间" min-width="190">
          <template #default="{ row }: { row: User }">{{ formatDateTimeShanghai(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }: { row: User }">
            <el-button
              size="small"
              type="success"
              :disabled="row.status === 'active'"
              @click="approveUser(row)"
            >
              审核通过
            </el-button>
            <el-button
              size="small"
              type="danger"
              :disabled="row.status === 'disabled' || row.id === currentUserId"
              @click="disableUser(row)"
            >
              禁用
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

@media (max-width: 720px) {
  .page-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
