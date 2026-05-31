<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { fetchAdminUsers } from '../api/adminUsers'
import {
  disableAgent,
  enableAgent,
  fetchAdminAgents,
  grantAgentPermission,
  type Agent,
  type AgentRiskLevel,
} from '../api/agents'
import type { User, UserRole } from '../api/auth'

const router = useRouter()
const loading = ref(false)
const usersLoading = ref(false)
const agents = ref<Agent[]>([])
const users = ref<User[]>([])
const permissionDialogVisible = ref(false)
const selectedAgent = ref<Agent | null>(null)
const permissionMode = ref<'role' | 'user'>('role')
const selectedRole = ref<UserRole>('user')
const selectedUserId = ref<number>()

const activeUsers = computed(() => users.value.filter((user) => user.status === 'active'))

function riskTagType(riskLevel: AgentRiskLevel) {
  if (riskLevel === 'high') {
    return 'danger'
  }
  if (riskLevel === 'medium') {
    return 'warning'
  }
  return 'success'
}

async function loadAgents() {
  loading.value = true
  try {
    agents.value = await fetchAdminAgents()
  } catch {
    ElMessage.error('Agent 管理列表加载失败')
  } finally {
    loading.value = false
  }
}

async function loadUsers() {
  usersLoading.value = true
  try {
    users.value = await fetchAdminUsers()
  } catch {
    ElMessage.error('用户列表加载失败')
  } finally {
    usersLoading.value = false
  }
}

async function setAgentStatus(agent: Agent, enabled: boolean) {
  try {
    if (enabled) {
      await enableAgent(agent.code)
      ElMessage.success('Agent 已启用')
    } else {
      await disableAgent(agent.code)
      ElMessage.success('Agent 已禁用')
    }
    await loadAgents()
  } catch {
    ElMessage.error('Agent 状态更新失败')
  }
}

async function openPermissionDialog(agent: Agent) {
  selectedAgent.value = agent
  permissionMode.value = 'role'
  selectedRole.value = 'user'
  selectedUserId.value = undefined
  permissionDialogVisible.value = true
  if (users.value.length === 0) {
    await loadUsers()
  }
}

async function submitPermission() {
  if (!selectedAgent.value) {
    return
  }

  if (permissionMode.value === 'user' && !selectedUserId.value) {
    ElMessage.warning('请选择授权用户')
    return
  }

  try {
    await grantAgentPermission(
      selectedAgent.value.code,
      permissionMode.value === 'role'
        ? { role: selectedRole.value }
        : { user_id: selectedUserId.value },
    )
    ElMessage.success('Agent 权限已授权')
    permissionDialogVisible.value = false
  } catch {
    ElMessage.error('Agent 权限授权失败')
  }
}

onMounted(loadAgents)
</script>

<template>
  <main class="admin-agents-page">
    <section class="admin-agents-shell">
      <div class="header-row">
        <div>
          <h1>Agent 管理</h1>
          <p>查看预置 Agent，控制启用状态，并给用户或角色授权。</p>
        </div>
        <div class="header-actions">
          <el-button @click="router.push({ name: 'agents' })">Agent 工作台</el-button>
          <el-button @click="router.push({ name: 'dashboard' })">返回首页</el-button>
          <el-button type="primary" :loading="loading" @click="loadAgents">刷新</el-button>
        </div>
      </div>

      <el-table v-loading="loading" :data="agents" border class="agents-table">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="description" label="描述" min-width="240" />
        <el-table-column prop="category" label="分类" width="120" />
        <el-table-column label="风险" width="110">
          <template #default="{ row }: { row: Agent }">
            <el-tag :type="riskTagType(row.risk_level)" effect="dark">{{ row.risk_level }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="能力" min-width="150">
          <template #default="{ row }: { row: Agent }">
            <div class="capability-tags">
              <el-tag :type="row.support_files ? 'success' : 'info'" plain>
                文件{{ row.support_files ? '支持' : '不支持' }}
              </el-tag>
              <el-tag :type="row.support_images ? 'success' : 'info'" plain>
                图片{{ row.support_images ? '支持' : '不支持' }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }: { row: Agent }">
            <el-tag :type="row.enabled ? 'success' : 'info'">
              {{ row.enabled ? '已启用' : '已禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }: { row: Agent }">
            <el-button
              size="small"
              :type="row.enabled ? 'warning' : 'success'"
              @click="setAgentStatus(row, !row.enabled)"
            >
              {{ row.enabled ? '禁用' : '启用' }}
            </el-button>
            <el-button size="small" type="primary" @click="openPermissionDialog(row)">
              授权
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-dialog v-model="permissionDialogVisible" title="Agent 授权" width="460px">
        <el-form label-width="92px">
          <el-form-item label="Agent">
            <span>{{ selectedAgent?.name }}</span>
          </el-form-item>
          <el-form-item label="授权对象">
            <el-radio-group v-model="permissionMode">
              <el-radio-button label="role">角色</el-radio-button>
              <el-radio-button label="user">用户</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="permissionMode === 'role'" label="角色">
            <el-select v-model="selectedRole" class="form-control">
              <el-option label="普通用户" value="user" />
              <el-option label="管理员" value="admin" />
            </el-select>
          </el-form-item>
          <el-form-item v-else label="用户">
            <el-select
              v-model="selectedUserId"
              class="form-control"
              filterable
              :loading="usersLoading"
              placeholder="选择用户"
            >
              <el-option
                v-for="user in activeUsers"
                :key="user.id"
                :label="`${user.display_name}（${user.username}）`"
                :value="user.id"
              />
            </el-select>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="permissionDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="submitPermission">确认授权</el-button>
        </template>
      </el-dialog>
    </section>
  </main>
</template>

<style scoped>
.admin-agents-page {
  min-height: 100vh;
  background: #f5f7fb;
  color: #1f2937;
}

.admin-agents-shell {
  width: min(1220px, calc(100% - 32px));
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

.agents-table {
  border-radius: 8px;
}

.capability-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.form-control {
  width: 100%;
}

@media (max-width: 720px) {
  .admin-agents-shell {
    width: min(100% - 24px, 1220px);
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
