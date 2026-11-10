import client from './client'
import type { StaffAvatar, StaffLandmarksRequest } from './types'

export type { StaffAvatar } from './types'

export const listStaffAvatars = () => client.get<StaffAvatar[]>('/api/staff/avatars/')

export const getStaffAvatar = (id: number) => client.get<StaffAvatar>(`/api/staff/avatars/${id}/`)

export const saveStaffAvatarLandmarks = (id: number, body: StaffLandmarksRequest) =>
  client.patch<StaffAvatar>(`/api/staff/avatars/${id}/landmarks/`, body)
