import client from './client'
import type { Job } from './types'

export type { Job } from './types'

export const getJob = (id: number) => client.get<Job>(`/api/jobs/${id}/`)
