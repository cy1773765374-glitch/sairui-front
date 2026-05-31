<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { fetchHealth, type HealthResponse } from '../api/health'
import { useAppStore } from '../stores/app'

const appStore = useAppStore()
const loading = ref(false)
const health = ref<HealthResponse | null>(null)
const errorMessage = ref('')

async function loadHealth() {
  loading.value = true
  errorMessage.value = ''

  try {
    health.value = await fetchHealth()
  } catch (error) {
    health.value = null
    errorMessage.value = '后端健康检查失败'
    ElMessage.error(errorMessage.value)
  } finally {
    loading.value = false
  }
}

onMounted(loadHealth)
</script>

<template>
  <main class="dashboard-page">
    <section class="dashboard-shell">
      <div class="header-row">
        <div>
          <h1>{{ appStore.systemName }}</h1>
          <p>当前版本：{{ appStore.phase }}</p>
        </div>
        <el-button type="primary" :loading="loading" @click="loadHealth">
          刷新状态
        </el-button>
      </div>

      <el-card class="status-card" shadow="never">
        <template #header>
          <span>后端健康检查结果</span>
        </template>

        <el-skeleton v-if="loading" :rows="3" animated />
        <el-result
          v-else-if="errorMessage"
          icon="error"
          title="连接失败"
          :sub-title="errorMessage"
        />
        <el-descriptions v-else-if="health" :column="1" border>
          <el-descriptions-item label="状态">
            <el-tag type="success">{{ health.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="服务">
            {{ health.service }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>
    </section>
  </main>
</template>

<style scoped>
.dashboard-page {
  min-height: 100vh;
  background: #f5f7fb;
  color: #1f2937;
}

.dashboard-shell {
  width: min(960px, calc(100% - 32px));
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

h1 {
  margin: 0;
  font-size: 30px;
  line-height: 1.25;
  font-weight: 700;
}

p {
  margin: 10px 0 0;
  color: #667085;
}

.status-card {
  border-radius: 8px;
}

@media (max-width: 640px) {
  .dashboard-shell {
    width: min(100% - 24px, 960px);
    padding: 28px 0;
  }

  .header-row {
    flex-direction: column;
  }

  h1 {
    font-size: 24px;
  }
}
</style>
