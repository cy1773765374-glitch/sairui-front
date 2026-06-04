import { pinyin } from 'pinyin-pro'

export const AGENT_GROUPS = ['全部', 'A-F', 'G-L', 'M-R', 'S-X', 'Y-Z', '其他'] as const
export type AgentGroup = (typeof AGENT_GROUPS)[number]

const CHINESE_RE = /[\u4e00-\u9fff]/

export function getAgentInitial(agentName: string): string {
  const first = agentName.trim().charAt(0)
  if (!first) {
    return '其他'
  }
  if (/^[A-Za-z]$/.test(first)) {
    return first.toUpperCase()
  }
  if (CHINESE_RE.test(first)) {
    const converted = pinyin(first, { toneType: 'none' }).trim()
    const initial = converted.charAt(0).toUpperCase()
    return /^[A-Z]$/.test(initial) ? initial : '其他'
  }
  return '其他'
}

export function getAgentGroup(agentName: string): Exclude<AgentGroup, '全部'> {
  const initial = getAgentInitial(agentName)
  if (initial >= 'A' && initial <= 'F') {
    return 'A-F'
  }
  if (initial >= 'G' && initial <= 'L') {
    return 'G-L'
  }
  if (initial >= 'M' && initial <= 'R') {
    return 'M-R'
  }
  if (initial >= 'S' && initial <= 'X') {
    return 'S-X'
  }
  if (initial >= 'Y' && initial <= 'Z') {
    return 'Y-Z'
  }
  return '其他'
}
