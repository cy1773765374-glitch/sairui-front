import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({
    phase: 'Phase 03',
    systemName: 'OpenClaw 多 Agent 企业工作台',
  }),
})
