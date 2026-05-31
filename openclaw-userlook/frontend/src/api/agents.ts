import { apiClient } from './client'
import type { UserRole } from './auth'

export type AgentRiskLevel = 'low' | 'medium' | 'high'

export interface Agent {
  id: number
  code: string
  name: string
  description: string | null
  openclaw_agent_id: string
  category: string | null
  enabled: boolean
  risk_level: AgentRiskLevel
  support_files: boolean
  support_images: boolean
  created_at: string
  updated_at: string
}

export interface AgentPermissionPayload {
  user_id?: number
  role?: UserRole
}

export interface AgentPermission {
  id: number
  agent_id: number
  user_id: number | null
  role: UserRole | null
  created_at: string
}

export async function fetchAgents(): Promise<Agent[]> {
  const response = await apiClient.get<Agent[]>('/api/agents')
  return response.data
}

export async function fetchAdminAgents(): Promise<Agent[]> {
  const response = await apiClient.get<Agent[]>('/api/admin/agents')
  return response.data
}

export async function enableAgent(agentCode: string): Promise<Agent> {
  const response = await apiClient.post<Agent>(`/api/admin/agents/${agentCode}/enable`)
  return response.data
}

export async function disableAgent(agentCode: string): Promise<Agent> {
  const response = await apiClient.post<Agent>(`/api/admin/agents/${agentCode}/disable`)
  return response.data
}

export async function grantAgentPermission(
  agentCode: string,
  payload: AgentPermissionPayload,
): Promise<AgentPermission> {
  const response = await apiClient.post<AgentPermission>(
    `/api/admin/agents/${agentCode}/permissions`,
    payload,
  )
  return response.data
}
