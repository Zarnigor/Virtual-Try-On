import client from './client'
import type { TryOnRequest, TryOnResponse } from './types'

export const startTryon = (params: TryOnRequest) =>
  client.post<TryOnResponse>('/api/tryon/', params)
