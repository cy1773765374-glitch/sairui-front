import { apiClient, TOKEN_STORAGE_KEY } from './client'
import type { TaskRun } from './runs'

export type MessageRole = 'user' | 'assistant' | 'system'

export interface Message {
  id: number
  conversation_id: number
  run_id: number | null
  role: MessageRole
  content: string
  raw_payload: Record<string, unknown> | null
  created_at: string
}

export interface Conversation {
  id: number
  user_id: number
  agent_id: number
  agent_code: string
  agent_name: string
  title: string
  is_title_manual?: boolean
  session_key: string
  created_at: string
  updated_at: string
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
  active_run: TaskRun | null
}

export interface CreateConversationPayload {
  agent_id: number
  title: string
}

export type LocalMessage = Omit<Message, 'id' | 'conversation_id' | 'raw_payload' | 'run_id'> & {
  id: number | string
  conversation_id?: number
  run_id?: number | null
  raw_payload?: Record<string, unknown> | null
  streaming?: boolean
}

export async function fetchConversations(): Promise<Conversation[]> {
  const response = await apiClient.get<Conversation[]>('/api/conversations')
  return response.data
}

export async function createConversation(
  payload: CreateConversationPayload,
): Promise<Conversation> {
  const response = await apiClient.post<Conversation>('/api/conversations', payload)
  return response.data
}

export async function fetchConversation(conversationId: number): Promise<ConversationDetail> {
  const response = await apiClient.get<ConversationDetail>(`/api/conversations/${conversationId}`)
  return response.data
}

export async function updateConversationTitle(
  conversationId: number,
  payload: { title: string },
): Promise<Conversation> {
  const response = await apiClient.patch<Conversation>(`/api/conversations/${conversationId}`, payload)
  return response.data
}

export async function deleteConversation(conversationId: number): Promise<void> {
  await apiClient.delete(`/api/conversations/${conversationId}`)
}

export function buildConversationWebSocketUrl(conversationId: number): string {
  const apiBase = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:10009'
  const url = new URL(`/api/ws/conversations/${conversationId}`, apiBase)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('token', localStorage.getItem(TOKEN_STORAGE_KEY) ?? '')
  return url.toString()
}
