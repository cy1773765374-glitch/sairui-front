import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({
    phase: 'Phase 04',
    systemName: 'OpenClaw 多 Agent 企业工作台',
  }),
})
