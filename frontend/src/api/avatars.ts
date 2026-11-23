import client from './client'
import type { Avatar } from './types'

export type { Avatar } from './types'

export const listAvatars = () => client.get<Avatar[]>('/api/avatars/')
