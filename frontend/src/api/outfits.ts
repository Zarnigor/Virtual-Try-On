import client from './client'
import type { Outfit } from './types'

export type { Outfit } from './types'

export const listOutfits = () => client.get<Outfit[]>('/api/outfits/')
export const getOutfit = (id: number) => client.get<Outfit>(`/api/outfits/${id}/`)
export const deleteOutfit = (id: number) => client.delete(`/api/outfits/${id}/`)
