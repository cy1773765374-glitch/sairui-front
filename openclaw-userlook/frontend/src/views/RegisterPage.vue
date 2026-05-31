<script setup lang="ts">
import { reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()
const router = useRouter()
const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
  display_name: '',
})

async function submitRegister() {
  loading.value = true
  try {
    await authStore.register(form)
    ElMessage.success('注册成功，请等待管理员审核')
    router.push({ name: 'login' })
  } catch {
    ElMessage.error('注册失败，请确认用户名未被占用')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-panel">
      <h1>注册账号</h1>
      <p>提交申请后账号状态为 pending，需要管理员审核通过后才能登录。</p>

      <el-form label-position="top" @submit.prevent="submitRegister">
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model="form.display_name" autocomplete="name" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" autocomplete="new-password" show-password />
        </el-form-item>
        <el-button class="submit-button" type="primary" native-type="submit" :loading="loading">
          提交注册
        </el-button>
      </el-form>

      <div class="auth-link">
        已有账号？
        <RouterLink to="/login">返回登录</RouterLink>
      </div>
    </section>
  </main>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: #eef2f7;
  color: #1f2937;
}

.auth-panel {
  width: min(420px, 100%);
  padding: 28px;
  border: 1px solid #d8dee9;
  border-radius: 8px;
  background: #ffffff;
}

h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1.25;
}

p {
  margin: 8px 0 24px;
  color: #667085;
  line-height: 1.6;
}

.submit-button {
  width: 100%;
}

.auth-link {
  margin-top: 18px;
  text-align: center;
  color: #667085;
}
</style>
