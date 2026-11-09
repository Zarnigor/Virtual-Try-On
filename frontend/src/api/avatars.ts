import client from './client'
import type { Avatar, NearestAvatarQuery } from './types'

export type { Avatar } from './types'

export const listAvatars = () => client.get<Avatar[]>('/api/avatars/')

export const nearestAvatar = (params: NearestAvatarQuery) =>
  client.get<Avatar>('/api/avatars/nearest/', { params })
