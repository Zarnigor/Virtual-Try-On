import client from './client'
import type { FitCheckResponse, FitMeasurements, TryOnRequest, TryOnResponse } from './types'

export const startTryon = (params: TryOnRequest) =>
  client.post<TryOnResponse>('/api/tryon/', params)

/** GET tryon/fit-check/ (docs/11): a garment that does not fit is a result, not an error. */
export const fitCheck = (
  base: 'avatar' | 'body', garmentIds: number[], avatarId?: number, measurements?: FitMeasurements,
) => client.get<FitCheckResponse>('/api/tryon/fit-check/', {
  params: { base, avatar_id: avatarId, garment_ids: garmentIds.join(','), ...(base === 'avatar' ? measurements : {}) },
})
