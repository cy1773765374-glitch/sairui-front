import { apiClient } from './client'
import type { UserFile } from './files'

export type TaskRunStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'success'
  | 'failed'
  | 'cancelled'
  | 'timeout'
  | 'stale'

export interface FetchRunsParams {
  agent_id?: number
  conversation_id?: number
  status?: TaskRunStatus | ''
  run_type?: string
  active_only?: boolean
}

export interface TaskRun {
  id: number
  user_id: number
  agent_id: number
  agent_code: string | null
  agent_name: string | null
  conversation_id: number | null
  status: TaskRunStatus
  input_text: string
  run_type: string
  priority: number
  output_text: string | null
  output_dir: string | null
  output_files_json: unknown | null
  raw_payload: unknown | null
  raw_payload_summary: unknown | null
  error_message: string | null
  queued_at: string | null
  started_at: string | null
  finished_at: string | null
  heartbeat_at: string | null
  cancel_requested: boolean
  timeout_seconds: number | null
  created_at: string
  updated_at: string
  output_files: UserFile[]
}

export function isActiveRunStatus(status?: TaskRunStatus | '' | null): boolean {
  return status === 'pending' || status === 'queued' || status === 'running'
}

export async function fetchRuns(params: FetchRunsParams = {}): Promise<TaskRun[]> {
  const response = await apiClient.get<TaskRun[]>('/api/runs', { params })
  return response.data
}

export async function fetchRun(runId: number): Promise<TaskRun> {
  const response = await apiClient.get<TaskRun>(`/api/runs/${runId}`)
  return response.data
}

export async function cancelRun(runId: number): Promise<TaskRun> {
  const response = await apiClient.post<TaskRun>(`/api/runs/${runId}/cancel`)
  return response.data
}
