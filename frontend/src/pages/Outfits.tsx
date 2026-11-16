import { useEffect, useState } from 'react'
import { listOutfits, deleteOutfit, type Outfit } from '../api/outfits'
import Spinner from '../components/Spinner'
import StatusChip from '../components/StatusChip'

export default function Outfits() {
  const [outfits, setOutfits] = useState<Outfit[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    listOutfits()
      .then(({ data }) => setOutfits(data))
      .catch(() => setError('Koʻrinishlarni yuklab boʻlmadi'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const handleDelete = async (id: number) => {
    if (!confirm('Bu obraz oʻchirilsinmi?')) return
    try {
      await deleteOutfit(id)
      setOutfits((prev) => prev.filter((o) => o.id !== id))
    } catch {
      alert('Oʻchirishda xato')
    }
  }

  return (
    <div className="page">
      <h1 className="page-title">Obrazlar</h1>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
          <Spinner size={40} />
        </div>
      ) : error ? (
        <p className="error-text">{error}</p>
      ) : outfits.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: 60 }}>
          <p style={{ color: 'var(--muted)', marginBottom: 16 }}>
            Hali obraz yoʻq. Kiyib koʻring, natija shu yerda saqlanadi.
          </p>
          <a href="/tryon" className="btn btn-primary">
            Kiyib koʻrish
          </a>
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
            gap: 20,
          }}
        >
          {outfits.map((o) => (
            <div
              key={o.id}
              className="card"
              style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}
            >
              <div
                style={{
                  height: 300,
                  background: 'var(--inset)',
                  borderRadius: 'var(--radius-md)',
                  overflow: 'hidden',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {o.result_url ? (
                  <img
                    src={o.result_url}
                    alt="Natija"
                    style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                  />
                ) : (
                  <span style={{ color: 'var(--muted)', fontSize: 36 }}>⏳</span>
                )}
              </div>

              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {o.garments.map((g) => (
                  <StatusChip key={g.id} status={g.type} />
                ))}
                {o.result_url && <StatusChip status="done" />}
              </div>

              <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                {new Date(o.created_at).toLocaleDateString('uz-UZ')}
              </div>

              <div style={{ display: 'flex', gap: 8, marginTop: 'auto' }}>
                {o.result_url && (
                  <a
                    href={o.result_url}
                    download={`outfit-${o.id}.png`}
                    className="btn btn-secondary btn-sm"
                    style={{ flex: 1, fontSize: 12 }}
                  >
                    Yuklab olish
                  </a>
                )}
                <button
                  className="btn btn-danger btn-sm"
                  onClick={() => handleDelete(o.id)}
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
