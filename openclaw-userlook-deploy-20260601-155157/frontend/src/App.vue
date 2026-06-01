<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import WorkbenchLayout from './components/WorkbenchLayout.vue'

const route = useRoute()
const useWorkbenchLayout = computed(() => Boolean(route.meta.requiresAuth))
</script>

<template>
  <WorkbenchLayout v-if="useWorkbenchLayout">
    <router-view />
  </WorkbenchLayout>
  <router-view v-else />
</template>
