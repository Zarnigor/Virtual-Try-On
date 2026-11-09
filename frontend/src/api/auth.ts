import client from './client'
import type { AuthResponse, LoginRequest, RegisterRequest, User } from './types'

export type { AuthResponse, User } from './types'

export const register = (data: RegisterRequest) =>
  client.post<AuthResponse>('/api/auth/register/', data)

export const login = (data: LoginRequest) =>
  client.post<AuthResponse>('/api/auth/login/', data)

export const getMe = () => client.get<User>('/api/auth/me/')

export const deleteAccount = () => client.delete('/api/auth/me/')
