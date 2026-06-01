import { apiClient } from './client'
import type { User } from './auth'

export async function fetchAdminUsers(): Promise<User[]> {
  const response = await apiClient.get<User[]>('/api/admin/users')
  return response.data
}

export async function approveAdminUser(userId: number): Promise<User> {
  const response = await apiClient.post<User>(`/api/admin/users/${userId}/approve`)
  return response.data
}

export async function disableAdminUser(userId: number): Promise<User> {
  const response = await apiClient.post<User>(`/api/admin/users/${userId}/disable`)
  return response.data
}
