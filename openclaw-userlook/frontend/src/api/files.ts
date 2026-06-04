import { apiClient } from './client'

export type FilePurpose = 'upload' | 'output' | 'temp'

export interface UserFile {
  id: number
  user_id: number
  original_name: string
  file_type: string
  mime_type?: string | null
  file_size: number
  purpose: FilePurpose
  created_at: string
  download_url: string
}

export interface FileUploadResponse {
  file_id: number
  id?: number
  file: UserFile
}

export interface DeleteSkippedItem {
  id: number
  reason: string
}

export interface BatchDeleteFilesResponse {
  deleted_ids: number[]
  skipped: DeleteSkippedItem[]
}

export async function fetchFiles(): Promise<UserFile[]> {
  const response = await apiClient.get<UserFile[]>('/api/files')
  return response.data
}

export async function uploadFile(file: File): Promise<FileUploadResponse> {
  const formData = new FormData()
  formData.append('upload', file)
  const response = await apiClient.post<FileUploadResponse>('/api/files/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
  return response.data
}

export async function downloadFile(file: UserFile): Promise<void> {
  const response = await apiClient.get<Blob>(`/api/files/${file.id}/download`, {
    responseType: 'blob',
    timeout: 120000,
  })
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = file.original_name
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export async function deleteFile(fileId: number): Promise<void> {
  await apiClient.delete(`/api/files/${fileId}`)
}

export async function batchDeleteFiles(fileIds: number[]): Promise<BatchDeleteFilesResponse> {
  const response = await apiClient.post<BatchDeleteFilesResponse>('/api/files/batch-delete', {
    file_ids: fileIds,
  })
  return response.data
}

export function formatFileSize(size: number): string {
  if (size < 1024) {
    return `${size} B`
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
