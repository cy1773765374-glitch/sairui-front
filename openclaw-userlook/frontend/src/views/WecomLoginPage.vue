<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'

import { fetchWeComLoginUrl } from '../api/wecom'

const route = useRoute()
const loading = ref(true)

async function startWeComLogin() {
  loading.value = true
  try {
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    const response = await fetchWeComLoginUrl(redirect)
    window.location.href = response.login_url
  } catch {
    ElMessage.error('企业微信授权地址获取失败')
    loading.value = false
  }
}

onMounted(startWeComLogin)
</script>

<template>
  <main class="auth-page">
    <section class="auth-panel">
      <h1>企业微信免登录</h1>
      <p>正在通过企业微信自建应用接入系统。</p>
      <el-button class="submit-button" type="primary" :loading="loading" @click="startWeComLogin">
        重新发起授权
      </el-button>
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
</style>
