import { apiClient } from './client'
import type { UserFile } from './files'

export type TaskRunStatus = 'pending' | 'running' | 'success' | 'failed' | 'cancelled'

export interface TaskRun {
  id: number
  user_id: number
  agent_id: number
  agent_code: string | null
  agent_name: string | null
  conversation_id: number | null
  status: TaskRunStatus
  input_text: string
  output_text: string | null
  output_dir: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  output_files: UserFile[]
}

export async function fetchRuns(): Promise<TaskRun[]> {
  const response = await apiClient.get<TaskRun[]>('/api/runs')
  return response.data
}

export async function fetchRun(runId: number): Promise<TaskRun> {
  const response = await apiClient.get<TaskRun>(`/api/runs/${runId}`)
  return response.data
}
