import axios from 'axios'

export interface HealthResponse {
  status: string
  service: string
}

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:10009',
  timeout: 5000,
})

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await apiClient.get<HealthResponse>('/api/health')
  return response.data
}
