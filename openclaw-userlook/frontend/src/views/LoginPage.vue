<script setup lang="ts">
import { reactive, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
})

async function submitLogin() {
  loading.value = true
  try {
    await authStore.login(form)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    router.push(redirect)
  } catch {
    ElMessage.error('用户名、密码错误，或账号尚未通过审核')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-panel">
      <h1>登录</h1>
      <p>使用已通过管理员审核的内部账号进入系统。</p>

      <el-form label-position="top" @submit.prevent="submitLogin">
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" autocomplete="current-password" show-password />
        </el-form-item>
        <el-button class="submit-button" type="primary" native-type="submit" :loading="loading">
          登录
        </el-button>
      </el-form>

      <div class="auth-link">
        没有账号？
        <RouterLink to="/register">申请注册</RouterLink>
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
