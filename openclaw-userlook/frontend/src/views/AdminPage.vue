<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ChatDotRound, User } from '@element-plus/icons-vue'

const router = useRouter()
</script>

<template>
  <section class="admin-home page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">Admin</p>
        <h1>管理后台</h1>
        <p>集中进入用户审核和 Agent 授权管理。</p>
      </div>
    </header>

    <div class="admin-grid">
      <el-card class="entry-card" shadow="never" @click="router.push({ name: 'admin-users' })">
        <el-icon class="entry-icon"><User /></el-icon>
        <h2>用户管理</h2>
        <p>审核新用户、查看账号状态、禁用不再允许访问的账号。</p>
        <el-button type="primary">进入用户管理</el-button>
      </el-card>

      <el-card class="entry-card" shadow="never" @click="router.push({ name: 'admin-agents' })">
        <el-icon class="entry-icon"><ChatDotRound /></el-icon>
        <h2>Agent 管理</h2>
        <p>查看 Agent 配置、启停状态，并按用户或角色授权访问。</p>
        <el-button type="primary">进入 Agent 管理</el-button>
      </el-card>
    </div>
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
h2,
p {
  margin: 0;
}

h1 {
  font-size: 28px;
  line-height: 1.25;
}

.page-heading p:last-child,
.entry-card p {
  margin-top: 8px;
  color: #6f7785;
  line-height: 1.6;
}

.admin-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}

.entry-card {
  cursor: pointer;
  border-radius: 8px;
}

.entry-card :deep(.el-card__body) {
  display: grid;
  gap: 14px;
}

.entry-icon {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: #eef3fe;
  color: #1a73e8;
  font-size: 22px;
}
</style>
