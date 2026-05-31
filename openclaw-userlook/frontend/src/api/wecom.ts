import { apiClient } from './client'
import type { LoginResponse } from './auth'

export interface WeComLoginUrlResponse {
  login_url: string
  mock: boolean
  message?: string
}

export interface WeComBinding {
  provider: string
  external_user_id?: string
  external_open_id?: string
  external_union_id?: string
  display_name?: string
  created_at: string
}

export interface WeComMeResponse {
  bound: boolean
  login_source: 'wecom'
  binding: WeComBinding | null
}

export async function fetchWeComLoginUrl(state = ''): Promise<WeComLoginUrlResponse> {
  const response = await apiClient.get<WeComLoginUrlResponse>('/api/wecom/login-url', {
    params: state ? { state } : undefined,
  })
  return response.data
}

export async function finishWeComLogin(code: string, state: string): Promise<LoginResponse> {
  const response = await apiClient.get<LoginResponse>('/api/wecom/callback', {
    params: { code, state },
  })
  return response.data
}

export async function fetchWeComMe(): Promise<WeComMeResponse> {
  const response = await apiClient.get<WeComMeResponse>('/api/wecom/me')
  return response.data
}
