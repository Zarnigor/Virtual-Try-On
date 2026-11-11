import client from './client'
import type {
  Body, BodyConfirmRequest, BodyUploadResponse, MeasurementsUpdateRequest, Sex,
} from './types'

export type { Body } from './types'

export const uploadBody = (photo: File, isAdultConfirmed: boolean, sex: Sex) => {
  const form = new FormData()
  form.append('photo', photo)
  form.append('is_adult_confirmed', String(isAdultConfirmed))
  form.append('sex', sex)
  return client.post<BodyUploadResponse>('/api/body/', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const getBody = () => client.get<Body>('/api/body/')

/** One-time choice for a body created before sex was required (409 SEX_ALREADY_SET afterwards). */
export const setBodySex = (sex: Sex) => client.patch<Body>('/api/body/sex/', { sex })

export const confirmBody = (data: BodyConfirmRequest) =>
  client.post<Body>('/api/body/confirm/', data)

export const updateMeasurements = (data: MeasurementsUpdateRequest) =>
  client.patch<Body>('/api/body/measurements/', data)

export const deleteBody = () => client.delete('/api/body/')
