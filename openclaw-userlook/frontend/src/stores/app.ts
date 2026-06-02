import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({
    systemName: 'OpenClaw 多 Agent 工作台',
  }),
})
