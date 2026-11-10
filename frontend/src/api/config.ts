import client from './client'
import type { AppConfig } from './types'

/** Public flags (no login needed). Cached: they only change when the backend restarts. */
let cached: Promise<AppConfig> | null = null

export const getConfig = (): Promise<AppConfig> => {
  if (!cached) {
    cached = client
      .get<AppConfig>('/api/config/')
      .then(({ data }) => data)
      .catch(() => {
        cached = null
        return { demo_mode: false }
      })
  }
  return cached
}
