import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({
    phase: 'Phase 07',
    systemName: 'OpenClaw 多 Agent 企业工作台',
  }),
})
