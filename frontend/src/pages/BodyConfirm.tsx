import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getBody, confirmBody, deleteBody, type Body } from '../api/bodies'
import type { BodyLandmarks } from '../api/types'
import Spinner from '../components/Spinner'

export default function BodyConfirm() {
  const navigate = useNavigate()
  const [body, setBody] = useState<Body | null>(null)
  const [loading, setLoading] = useState(true)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getBody()
      .then(({ data }) => setBody(data))
      .catch(() => setBody(null))
      .finally(() => setLoading(false))
  }, [])

  const handleConfirm = async () => {
    if (!body) return
    setConfirming(true)
    try {
      // TODO(step 5): landmarks come from the LandmarkEditor; until it exists the backend
      // rejects an empty set with "Avval chiziqlarni belgilang."
      await confirmBody({ landmarks: body.landmarks as BodyLandmarks })
      navigate('/body/measurements')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Tasdiqlashda xato')
    } finally {
      setConfirming(false)
    }
  }

  const handleReupload = async () => {
    if (!confirm('Joriy tana oʻchiriladi. Davom etilsinmi?')) return
    try {
      await deleteBody()
      navigate('/body/upload')
    } catch {
      setError('Oʻchirishda xato')
    }
  }

  if (loading) {
    return (
      <div className="page" style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
        <Spinner size={40} />
      </div>
    )
  }

  if (!body) {
    return (
      <div className="page">
        <p style={{ color: 'var(--muted)' }}>Tana topilmadi. <a href="/body/upload">Yuklash</a></p>
      </div>
    )
  }

  return (
    <div className="page" style={{ maxWidth: 560 }}>
      <h1 className="page-title">Tana rasmini tasdiqlash</h1>

      <div className="card" style={{ marginBottom: 24 }}>
        {body.image_url && (
          <img
            src={body.image_url}
            alt="Tana rasmi"
            style={{
              width: '100%',
              maxHeight: 500,
              objectFit: 'contain',
              borderRadius: 'var(--radius-md)',
              background: 'var(--inset)',
              marginBottom: 16,
            }}
          />
        )}
        <p style={{ color: 'var(--text-soft)', fontSize: 14 }}>
          Rasm tasdiqlanganidan soʻng, uni oʻzgartirish mumkin boʻlmaydi. Iltimos diqqat bilan tekshiring.
        </p>
      </div>

      {error && <p className="error-text" style={{ marginBottom: 12 }}>{error}</p>}

      <div style={{ display: 'flex', gap: 12 }}>
        <button className="btn btn-primary" onClick={handleConfirm} disabled={confirming} style={{ flex: 1 }}>
          {confirming ? 'Kutilmoqda…' : 'Tasdiqlash'}
        </button>
        <button className="btn btn-secondary" onClick={handleReupload}>
          Qayta yuklash
        </button>
      </div>
    </div>
  )
}
