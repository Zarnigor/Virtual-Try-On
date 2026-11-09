import { Navigate } from 'react-router-dom'
import { useAuthStore } from '../store/auth'

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const access = useAuthStore((s) => s.access)
  if (!access) return <Navigate to="/login" replace />
  return <>{children}</>
}
