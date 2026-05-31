import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({
    phase: 'Phase 08',
    systemName: 'OpenClaw 多 Agent 工作台',
  }),
})
