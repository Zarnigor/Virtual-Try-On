import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listStaffAvatars, type StaffAvatar } from '../../api/staff'
import Spinner from '../../components/Spinner'
import StatusChip from '../../components/StatusChip'

const SEX: Record<string, string> = { male: 'Erkak', female: 'Ayol' }
const BUILD: Record<string, string> = { slim: 'Ozgʻin', average: 'Oʻrtacha', plus: 'Toʻla' }

/** Staff: every avatar with its landmark status; opens the editor. */
export default function StaffAvatars() {
  const [avatars, setAvatars] = useState<StaffAvatar[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    listStaffAvatars()
      .then(({ data }) => setAvatars(data))
      .catch(() => setError('Avatarlarni yuklab boʻlmadi'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="page">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24, gap: 12, flexWrap: 'wrap' }}>
        <h1 className="page-title" style={{ margin: 0 }}>Avatarlar</h1>
        <Link to="/staff/avatars/new" className="btn btn-primary">+ Yangi avatar</Link>
      </div>
      {loading && <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}><Spinner size={40} /></div>}
      {error && <p className="error-text">{error}</p>}
      {!loading && !error && avatars.length === 0 && (
        <p style={{ color: 'var(--muted)' }}>Hali avatar yoʻq. Yangi avatar yuklang.</p>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 16 }}>
        {avatars.map((a) => (
          <Link key={a.id} to={`/staff/avatars/${a.id}`} className="card" style={{ textDecoration: 'none', color: 'inherit', padding: 12 }}>
            <div style={{ aspectRatio: '1 / 2', background: 'var(--inset)', borderRadius: 'var(--radius-sm)', overflow: 'hidden', marginBottom: 10 }}>
              {a.image_url && <img src={a.image_url} alt={`${SEX[a.sex]} ${BUILD[a.build]}`} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />}
            </div>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>{SEX[a.sex]} · {BUILD[a.build]}</div>
            <StatusChip status={a.status} />
          </Link>
        ))}
      </div>
    </div>
  )
}
