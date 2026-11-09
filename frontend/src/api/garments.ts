import client from './client'
import type {
  Garment, GarmentLandmarks, GarmentScope, GarmentType, GarmentUploadResponse, Visibility,
} from './types'

export type { Garment } from './types'

export const uploadGarment = (photo: File, type: GarmentType, name = '') => {
  const form = new FormData()
  form.append('photo', photo)
  form.append('type', type)
  if (name) form.append('name', name)
  return client.post<GarmentUploadResponse>('/api/garments/', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const listGarments = (scope: GarmentScope = 'mine', type?: GarmentType) =>
  client.get<Garment[]>('/api/garments/', { params: { scope, type } })

export const getGarment = (id: number) => client.get<Garment>(`/api/garments/${id}/`)

export const updateLandmarks = (id: number, landmarks: GarmentLandmarks) =>
  client.patch<Garment>(`/api/garments/${id}/landmarks/`, { landmarks })

export const updateVisibility = (id: number, visibility: Visibility) =>
  client.patch<Garment>(`/api/garments/${id}/visibility/`, { visibility })

export const deleteGarment = (id: number) => client.delete(`/api/garments/${id}/`)
