import client from './client'
import type {
  ForSex, Garment, GarmentGender, GarmentLandmarks, GarmentLandmarksResponse, GarmentScope, GarmentSettings, GarmentSizes,
  GarmentType,
  GarmentUploadResponse, Visibility,
} from './types'

export type { Garment } from './types'

/** `sizes` is required by the backend (400 SIZES_INVALID without it); the upload form that collects it is docs/11 step 4. */
export const uploadGarment = (photo: File, type: GarmentType, sizes?: GarmentSizes, stretch = false, name = '') => {
  const form = new FormData()
  form.append('photo', photo)
  form.append('type', type)
  if (sizes) form.append('sizes', JSON.stringify(sizes))
  form.append('stretch', String(stretch))
  if (name) form.append('name', name)
  return client.post<GarmentUploadResponse>('/api/garments/', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/** gender: female / male also return unisex garments. forSex: the try-on rule (male / female + unisex; all = off). */
export const listGarments = (
  scope: GarmentScope = 'mine', type?: GarmentType, gender?: GarmentGender, forSex?: ForSex,
) => client.get<Garment[]>('/api/garments/', { params: { scope, type, gender, for_sex: forSex } })

/** docs/09 #97: unisex always fits; otherwise the garment gender must equal the base sex. */
export const garmentFitsSex = (gender: GarmentGender, sex: 'male' | 'female') => gender === 'unisex' || gender === sex

export const getGarment = (id: number) => client.get<Garment>(`/api/garments/${id}/`)

export const updateLandmarks = (id: number, landmarks: GarmentLandmarks) =>
  client.patch<GarmentLandmarksResponse>(`/api/garments/${id}/landmarks/`, { landmarks })

export const updateVisibility = (id: number, visibility: Visibility) =>
  client.patch<Garment>(`/api/garments/${id}/visibility/`, { visibility })

/** fit_mode / gender, same style as visibility. */
export const updateGarmentSettings = (id: number, settings: GarmentSettings) =>
  client.patch<Garment>(`/api/garments/${id}/`, settings)

/** FULL replace of sizes (docs/11). */
export const updateGarmentSizes = (id: number, sizes: GarmentSizes, stretch?: boolean) =>
  client.patch<Garment>(`/api/garments/${id}/sizes/`, { sizes, stretch })

export const deleteGarment = (id: number) => client.delete(`/api/garments/${id}/`)
