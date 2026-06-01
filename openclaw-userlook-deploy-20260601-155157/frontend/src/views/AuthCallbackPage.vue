<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { finishWeComLogin } from '../api/wecom'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(true)
const errorMessage = ref('')

async function finishLogin() {
  const code = typeof route.query.code === 'string' ? route.query.code : ''
  const state = typeof route.query.state === 'string' ? route.query.state : ''
  if (!code) {
    errorMessage.value = '缺少企业微信授权 code'
    loading.value = false
    return
  }

  try {
    const response = await finishWeComLogin(code, state)
    authStore.setSession(response.access_token, response.user, 'wecom')
    const redirect = state.startsWith('/') && !state.startsWith('//') ? state : '/'
    router.replace(redirect)
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    errorMessage.value = detail || '企业微信免登录失败，请联系管理员'
  } finally {
    loading.value = false
  }
}

onMounted(finishLogin)
</script>

<template>
  <main class="auth-page">
    <section class="auth-panel">
      <h1>企业微信登录</h1>
      <p v-if="loading">正在完成企业微信身份校验。</p>
      <template v-else-if="errorMessage">
        <p>{{ errorMessage }}</p>
        <RouterLink to="/login">返回账号密码登录</RouterLink>
      </template>
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
</style>
