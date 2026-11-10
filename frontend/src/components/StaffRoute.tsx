import { Navigate } from 'react-router-dom'
import Spinner from './Spinner'
import { useMe } from './useMe'

/** Staff-only pages. The backend enforces it too (non-staff get 404); this only hides the screens. */
export default function StaffRoute({ children }: { children: React.ReactNode }) {
  const user = useMe()
  if (!user) {
    return (
      <div className="page" style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
        <Spinner size={40} />
      </div>
    )
  }
  if (!user.is_staff) return <Navigate to="/" replace />
  return <>{children}</>
}
