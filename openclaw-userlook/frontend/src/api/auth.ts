import { apiClient } from './client'

export type UserStatus = 'pending' | 'active' | 'disabled'
export type UserRole = 'admin' | 'user'

export interface User {
  id: number
  username: string
  display_name: string
  status: UserStatus
  role: UserRole
  created_at: string
  updated_at: string
}

export interface RegisterPayload {
  username: string
  password: string
  display_name: string
}

export interface LoginPayload {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: User
}

export async function register(payload: RegisterPayload): Promise<User> {
  const response = await apiClient.post<User>('/api/auth/register', payload)
  return response.data
}

export async function login(payload: LoginPayload): Promise<LoginResponse> {
  const response = await apiClient.post<LoginResponse>('/api/auth/login', payload)
  return response.data
}

export async function fetchMe(): Promise<User> {
  const response = await apiClient.get<User>('/api/auth/me')
  return response.data
}
