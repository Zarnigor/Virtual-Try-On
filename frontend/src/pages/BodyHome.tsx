import { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { getBody, type Body } from '../api/bodies'
import Spinner from '../components/Spinner'
import StatusChip from '../components/StatusChip'
import { BODY_TEXT } from '../locale/uz'

/** "Tana" in the nav: no body -> upload, unconfirmed -> confirm page, confirmed -> the locked body card. */
export default function BodyHome() {
  const [body, setBody] = useState<Body | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getBody().then(({ data }) => setBody(data)).catch(() => setBody(null)).finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="page" style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
        <Spinner size={40} />
      </div>
    )
  }
  if (!body) return <Navigate to="/body/upload" replace />
  if (!body.confirmed_at) return <Navigate to="/body/confirm" replace />

  return (
    <div className="page" style={{ maxWidth: 560 }}>
      <h1 className="page-title">{BODY_TEXT.title}</h1>
      <div className="card">
        {body.image_url && (
          <img
            src={body.image_url}
            alt={BODY_TEXT.imageAlt}
            style={{
              width: '100%', maxHeight: 520, objectFit: 'contain', borderRadius: 'var(--radius-md)',
              background: 'var(--inset)', marginBottom: 16,
            }}
          />
        )}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
          <StatusChip status="approved" />
          <StatusChip status="private" />
        </div>
        <p style={{ color: 'var(--text-soft)', fontSize: 14, marginBottom: 16 }}>{BODY_TEXT.lockedNote}</p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Link to="/tryon" className="btn btn-primary btn-sm">{BODY_TEXT.tryOn}</Link>
          <Link to="/body/measurements" className="btn btn-secondary btn-sm">{BODY_TEXT.measurements}</Link>
          <Link to="/profile" className="btn btn-secondary btn-sm">{BODY_TEXT.profile}</Link>
        </div>
      </div>
    </div>
  )
}
