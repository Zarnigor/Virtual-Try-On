import client from './client'
import type { FitCheckResponse, TryOnRequest, TryOnResponse } from './types'

export const startTryon = (params: TryOnRequest) =>
  client.post<TryOnResponse>('/api/tryon/', params)

/** GET tryon/fit-check/ (docs/11): a garment that does not fit is a result, not an error. The check uses the
 *  rendered Body's / Avatar's own sizes (docs/09 #129): no measurements are sent. */
export const fitCheck = (base: 'avatar' | 'body', garmentIds: number[], avatarId?: number) =>
  client.get<FitCheckResponse>('/api/tryon/fit-check/', {
    params: { base, avatar_id: avatarId, garment_ids: garmentIds.join(',') },
  })
