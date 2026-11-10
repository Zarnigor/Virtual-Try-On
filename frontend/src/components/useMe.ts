import { useEffect } from 'react'
import { getMe } from '../api/auth'
import { useAuthStore } from '../store/auth'

/** The logged-in user, fetched once if the store is empty (after a page reload). */
export function useMe() {
  const { access, user, setUser } = useAuthStore()
  useEffect(() => {
    if (access && !user) getMe().then(({ data }) => setUser(data)).catch(() => {})
  }, [access, user, setUser])
  return user
}
