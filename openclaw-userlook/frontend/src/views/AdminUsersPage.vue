<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { approveAdminUser, disableAdminUser, fetchAdminUsers } from '../api/adminUsers'
import type { User, UserStatus } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
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
  <main class="admin-page">
    <section class="admin-shell">
      <div class="header-row">
        <div>
          <h1>用户审核</h1>
          <p>审核 pending 用户，或禁用不再允许登录的账号。</p>
        </div>
        <div class="header-actions">
          <el-button @click="router.push({ name: 'dashboard' })">返回工作台</el-button>
          <el-button type="primary" :loading="loading" @click="loadUsers">刷新</el-button>
        </div>
      </div>

      <el-table v-loading="loading" :data="users" border class="users-table">
        <el-table-column prop="username" label="用户名" min-width="140" />
        <el-table-column prop="display_name" label="显示名称" min-width="140" />
        <el-table-column label="角色" width="110">
          <template #default="{ row }: { row: User }">
            <el-tag :type="row.role === 'admin' ? 'warning' : 'info'">{{ row.role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }: { row: User }">
            <el-tag :type="statusTagType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="注册时间" min-width="190" />
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
    </section>
  </main>
</template>

<style scoped>
.admin-page {
  min-height: 100vh;
  background: #f5f7fb;
  color: #1f2937;
}

.admin-shell {
  width: min(1100px, calc(100% - 32px));
  margin: 0 auto;
  padding: 48px 0;
}

.header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
}

.header-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

h1 {
  margin: 0;
  font-size: 30px;
  line-height: 1.25;
}

p {
  margin: 10px 0 0;
  color: #667085;
}

.users-table {
  border-radius: 8px;
}

@media (max-width: 720px) {
  .admin-shell {
    width: min(100% - 24px, 1100px);
    padding: 28px 0;
  }

  .header-row {
    flex-direction: column;
  }

  .header-actions {
    justify-content: flex-start;
  }
}
</style>
