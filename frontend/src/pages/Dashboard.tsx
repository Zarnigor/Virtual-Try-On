import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getBody, type Body } from '../api/bodies'
import { useAuthStore } from '../store/auth'
import { getMe } from '../api/auth'
import Spinner from '../components/Spinner'
import StatusChip from '../components/StatusChip'

export default function Dashboard() {
  const { setUser } = useAuthStore()
  const [body, setBody] = useState<Body | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getMe().then(({ data }) => setUser(data)).catch(() => {})
    getBody()
      .then(({ data }) => setBody(data))
      .catch(() => setBody(null))
      .finally(() => setLoading(false))
  }, [setUser])

  return (
    <div className="page">
      <h1 className="page-title">Bosh sahifa</h1>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 20 }}>
        {/* Body card */}
        <div className="card">
          <h2 style={{ fontSize: 18, marginBottom: 16 }}>Mening tanam</h2>
          {loading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 24 }}>
              <Spinner />
            </div>
          ) : body ? (
            <div>
              {body.image_url && (
                <img
                  src={body.image_url}
                  alt="Tana rasmi"
                  style={{
                    width: '100%',
                    maxHeight: 200,
                    objectFit: 'contain',
                    borderRadius: 'var(--radius-md)',
                    marginBottom: 12,
                    background: 'var(--inset)',
                  }}
                />
              )}
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
                <StatusChip status={body.confirmed_at ? 'approved' : 'pending'} />
                {body.measurements && <StatusChip status="done" />}
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {!body.confirmed_at && (
                  <Link to="/body/confirm" className="btn btn-primary btn-sm">
                    Tasdiqlash
                  </Link>
                )}
                <Link to="/body/measurements" className="btn btn-secondary btn-sm">
                  Oʻlchovlar
                </Link>
              </div>
            </div>
          ) : (
            <div>
              <p style={{ color: 'var(--muted)', fontSize: 14, marginBottom: 16 }}>
                Hali tana yuklanmagan. Virtual kiyinish uchun tana rasmingizni yuklang.
              </p>
              <Link to="/body/upload" className="btn btn-primary btn-sm">
                Tana yuklash
              </Link>
            </div>
          )}
        </div>

        {/* Quick links */}
        <div className="card">
          <h2 style={{ fontSize: 18, marginBottom: 16 }}>Tez havolalar</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <Link
              to="/wardrobe"
              className="btn btn-secondary"
              style={{ justifyContent: 'flex-start' }}
            >
              👕 Liboslarim
            </Link>
            <Link
              to="/tryon"
              className="btn btn-secondary"
              style={{ justifyContent: 'flex-start' }}
            >
              ✨ Sinab koʻrish
            </Link>
            <Link
              to="/outfits"
              className="btn btn-secondary"
              style={{ justifyContent: 'flex-start' }}
            >
              🗂 Saqlangan koʻrinishlar
            </Link>
          </div>
        </div>

        {/* Info card */}
        <div className="card">
          <h2 style={{ fontSize: 18, marginBottom: 16 }}>Qanday foydalanish</h2>
          <ol style={{ paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[
              'Tana rasmingizni yuklang (A-poza)',
              'Tana oʻlchovlarini kiriting',
              'Kiyim rasmlarini yuklang',
              'Kiyimda belgi nuqtalarini qoʻying',
              'Virtual kiyinishni boshlang',
            ].map((step, i) => (
              <li key={i} style={{ color: 'var(--text-soft)', fontSize: 14 }}>
                <strong style={{ color: 'var(--accent)', marginRight: 6 }}>{i + 1}.</strong>
                {step}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  )
}
