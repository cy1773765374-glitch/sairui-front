import { apiClient } from './client'
import type { AgentRiskLevel } from './agents'

export interface FavoriteAgent {
  agent_code: string
  name: string
  description: string | null
  risk_level: AgentRiskLevel
  category: string | null
  support_files: boolean
  support_images: boolean
  sort_order: number
  created_at: string
  updated_at: string
}

export async function fetchFavoriteAgents(): Promise<FavoriteAgent[]> {
  const response = await apiClient.get<FavoriteAgent[]>('/api/me/favorite-agents')
  return response.data
}

export async function addFavoriteAgent(agentCode: string): Promise<FavoriteAgent> {
  const response = await apiClient.post<FavoriteAgent>('/api/me/favorite-agents', {
    agent_code: agentCode,
  })
  return response.data
}

export async function removeFavoriteAgent(agentCode: string): Promise<void> {
  await apiClient.delete(`/api/me/favorite-agents/${agentCode}`)
}

export async function reorderFavoriteAgents(agentCodes: string[]): Promise<FavoriteAgent[]> {
  const response = await apiClient.put<FavoriteAgent[]>('/api/me/favorite-agents/reorder', {
    agent_codes: agentCodes,
  })
  return response.data
}
