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
  openclaw_agent_id: string | null
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
  task_kind: string | null
  runner_name: string | null
  workspace_path: string | null
  phase: string | null
  progress_message: string | null
  duration_seconds: number | null
  client_message_id: string | null
  gateway_session_key: string | null
  idempotency_key: string | null
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

export interface DeleteSkippedItem {
  id: number
  reason: string
}

export interface BatchDeleteRunsResponse {
  deleted_ids: number[]
  skipped: DeleteSkippedItem[]
}

export function isActiveRunStatus(status?: TaskRunStatus | '' | null): boolean {
  return status === 'pending' || status === 'queued' || status === 'running'
}

export function isTerminalRunStatus(status?: TaskRunStatus | '' | null): boolean {
  return status === 'success' || status === 'failed' || status === 'cancelled' || status === 'timeout' || status === 'stale'
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

export async function deleteRun(runId: number): Promise<void> {
  await apiClient.delete(`/api/runs/${runId}`)
}

export async function batchDeleteRuns(runIds: number[]): Promise<BatchDeleteRunsResponse> {
  const response = await apiClient.post<BatchDeleteRunsResponse>('/api/runs/batch-delete', {
    run_ids: runIds,
  })
  return response.data
}
