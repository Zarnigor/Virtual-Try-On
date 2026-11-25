import client from './client'
import type { Build, Sex, StaffAvatar, StaffLandmarksRequest } from './types'

export type { StaffAvatar } from './types'

export const listStaffAvatars = () => client.get<StaffAvatar[]>('/api/staff/avatars/')

export const getStaffAvatar = (id: number) => client.get<StaffAvatar>(`/api/staff/avatars/${id}/`)

export const saveStaffAvatarLandmarks = (id: number, body: StaffLandmarksRequest) =>
  client.patch<StaffAvatar>(`/api/staff/avatars/${id}/landmarks/`, body)

export interface StaffAvatarUpload {
  sex: Sex
  build: Build
  photo: File
  height_cm: number
  shoulder: number
  chest: number
  waist: number
  hip: number
  /** cm, a WIDTH; default: computed from the new landmarks (docs/09 #129). */
  shoulder_width?: number
}

/** POST staff/avatars/ (multipart). 201 new, 200 replaced (landmarks reset to auto); 400 {code, detail}. */
export const uploadStaffAvatar = (data: StaffAvatarUpload) => {
  const form = new FormData()
  Object.entries(data).forEach(([k, v]) => form.append(k, v instanceof File ? v : String(v)))
  return client.post<StaffAvatar & { warnings: string[] }>('/api/staff/avatars/', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
