import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/auth'
import DemoBadge from './DemoBadge'

export default function Layout() {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const navStyle = ({ isActive }: { isActive: boolean }): React.CSSProperties => ({
    display: 'flex',
    alignItems: 'center',
    padding: '8px 14px',
    borderRadius: 'var(--radius-sm)',
    fontSize: 14,
    fontWeight: 500,
    color: isActive ? 'var(--accent)' : 'var(--text-soft)',
    background: isActive ? 'var(--selected)' : 'transparent',
    textDecoration: 'none',
    transition: 'color 0.15s, background 0.15s',
  })

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <header
        style={{
          background: 'var(--header)',
          borderBottom: '1px solid var(--border)',
          position: 'sticky',
          top: 0,
          zIndex: 100,
        }}
      >
        <div
          style={{
            maxWidth: 1120,
            margin: '0 auto',
            padding: '0 32px',
            height: 60,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <span
            style={{
              fontFamily: "'Space Grotesk', sans-serif",
              fontWeight: 700,
              fontSize: 18,
              color: 'var(--accent)',
              marginRight: 24,
              letterSpacing: '-0.01em',
            }}
          >
            TryOn Studio
          </span>
          <DemoBadge />
          <nav style={{ display: 'flex', gap: 4, flex: 1 }}>
            <NavLink to="/" end style={navStyle}>Bosh sahifa</NavLink>
            <NavLink to="/wardrobe" style={navStyle}>Liboslar</NavLink>
            <NavLink to="/tryon" style={navStyle}>Sinab koʻrish</NavLink>
            <NavLink to="/outfits" style={navStyle}>Koʻrinishlar</NavLink>
          </nav>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {user && (
              <span style={{ fontSize: 13, color: 'var(--muted)' }}>{user.email}</span>
            )}
            <button className="btn btn-secondary btn-sm" onClick={handleLogout}>
              Chiqish
            </button>
          </div>
        </div>
      </header>
      <main style={{ flex: 1 }}>
        <Outlet />
      </main>
    </div>
  )
}
