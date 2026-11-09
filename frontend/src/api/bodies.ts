import client from './client'
import type {
  Body, BodyConfirmRequest, BodyUploadResponse, MeasurementsUpdateRequest,
} from './types'

export type { Body } from './types'

export const uploadBody = (photo: File, isAdultConfirmed: boolean) => {
  const form = new FormData()
  form.append('photo', photo)
  form.append('is_adult_confirmed', String(isAdultConfirmed))
  return client.post<BodyUploadResponse>('/api/body/', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const getBody = () => client.get<Body>('/api/body/')

export const confirmBody = (data: BodyConfirmRequest) =>
  client.post<Body>('/api/body/confirm/', data)

export const updateMeasurements = (data: MeasurementsUpdateRequest) =>
  client.patch<Body>('/api/body/measurements/', data)

export const deleteBody = () => client.delete('/api/body/')
