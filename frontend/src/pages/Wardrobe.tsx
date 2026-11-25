import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listGarments, deleteGarment, type Garment } from '../api/garments'
import Spinner from '../components/Spinner'
import DevAiWarning from '../components/DevAiWarning'
import { GenderBadge } from '../components/GarmentSettingsPanel'
import StatusChip from '../components/StatusChip'
import { FIT_TEXT } from '../locale/uz'

export default function Wardrobe() {
  const [garments, setGarments] = useState<Garment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    listGarments('mine')
      .then(({ data }) => setGarments(data))
      .catch(() => setError('Kiyimlarni yuklab boʻlmadi'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  // A garment has no image_url until its cleaning job is done: refresh quietly until all are ready.
  const preparing = garments.some((g) => !g.image_url)
  useEffect(() => {
    if (!preparing) return
    const t = setInterval(() => {
      listGarments('mine').then(({ data }) => setGarments(data)).catch(() => {})
    }, 3000)
    return () => clearInterval(t)
  }, [preparing])

  const handleDelete = async (id: number) => {
    if (!confirm('Bu libosni oʻchirilsinmi?')) return
    try {
      await deleteGarment(id)
      setGarments((prev) => prev.filter((g) => g.id !== id))
    } catch {
      alert('Oʻchirishda xato')
    }
  }

  return (
    <div className="page">
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 24, gap: 16 }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, flex: 1 }}>Kiyimlar</h1>
        <Link to="/garments/upload" className="btn btn-primary">
          + Kiyim yuklash
        </Link>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
          <Spinner size={40} />
        </div>
      ) : error ? (
        <p className="error-text">{error}</p>
      ) : garments.length === 0 ? (
        <div
          className="card"
          style={{ textAlign: 'center', padding: 60 }}
        >
          <p style={{ color: 'var(--muted)', marginBottom: 20 }}>
            Hali hech qanday kiyim yuklanmagan
          </p>
          <Link to="/garments/upload" className="btn btn-primary">
            Birinchi kiyimni yuklash
          </Link>
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
            gap: 16,
          }}
        >
          {garments.map((g) => (
            <div
              key={g.id}
              className="card"
              style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}
            >
              <div
                style={{
                  height: 180,
                  background: 'var(--inset)',
                  borderRadius: 'var(--radius-md)',
                  overflow: 'hidden',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {g.image_url ? (
                  <img
                    src={g.image_url}
                    alt="Kiyim"
                    style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                  />
                ) : (
                  <span style={{ color: 'var(--muted)', fontSize: 13 }}>Tayyorlanmoqda…</span>
                )}
              </div>

              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {g.ai_skipped && <DevAiWarning compact />}
                <StatusChip status={g.type} />
                <GenderBadge gender={g.gender} />
                {/* Moderation status only matters for public garments (private ones stay "pending"). */}
                <StatusChip status={g.visibility === 'public' ? g.status : g.visibility} />
                {!g.image_url ? (
                  <StatusChip status="preparing" />
                ) : g.landmarks && Object.keys(g.landmarks).length > 0 ? (
                  <StatusChip status="marked" />
                ) : (
                  <StatusChip status="unmarked" />
                )}
                {g.image_url && g.neck_complete === false && <StatusChip status="neck_unmarked" />}
                {g.owned_by_me && !g.sizes_complete && <StatusChip status="sizes_missing" />}
              </div>

              <div style={{ display: 'flex', gap: 8, marginTop: 'auto' }}>
                {g.image_url ? (
                  <Link
                    to={`/garments/${g.id}/landmarks`}
                    className="btn btn-secondary btn-sm"
                    style={{ flex: 1, fontSize: 12 }}
                  >
                    Belgilar
                  </Link>
                ) : (
                  <button className="btn btn-secondary btn-sm" style={{ flex: 1, fontSize: 12 }} disabled>
                    Tayyorlanmoqda…
                  </button>
                )}
                {g.owned_by_me && (
                  <Link to={`/garments/${g.id}/sizes`} className="btn btn-secondary btn-sm" style={{ fontSize: 12 }}>
                    {FIT_TEXT.sizesLink}
                  </Link>
                )}
                <button
                  className="btn btn-danger btn-sm"
                  onClick={() => handleDelete(g.id)}
                  aria-label="Oʻchirish"
                >
                  Oʻchirish
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
