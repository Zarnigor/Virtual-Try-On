import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { getBody, type Body } from '../api/bodies'
import { listGarments, type Garment } from '../api/garments'
import { listOutfits, type Outfit } from '../api/outfits'
import Spinner from '../components/Spinner'
import StatusChip from '../components/StatusChip'
import { BODY_TEXT, HOME } from '../locale/uz'

const thumb: React.CSSProperties = {
  height: 150, background: 'var(--inset)', borderRadius: 'var(--radius-md)', overflow: 'hidden',
  display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 10,
}

function Section({ title, to, children }: { title: string; to: string; children: ReactNode }) {
  return (
    <section style={{ marginBottom: 28 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', marginBottom: 12 }}>
        <h2 style={{ fontSize: 18, flex: 1 }}>{title}</h2>
        <Link to={to} style={{ fontSize: 13, color: 'var(--accent)' }}>{HOME.all}</Link>
      </div>
      {children}
    </section>
  )
}

/** Screen 2: the body card, the newest garments and the newest outfits. Everything comes from the API. */
export default function Dashboard() {
  const [body, setBody] = useState<Body | null>(null)
  const [garments, setGarments] = useState<Garment[]>([])
  const [outfits, setOutfits] = useState<Outfit[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([
      getBody().then(({ data }) => setBody(data)).catch(() => setBody(null)),  // 404 = no body yet
      listGarments('mine').then(({ data }) => setGarments(data)),
      listOutfits().then(({ data }) => setOutfits(data)),
    ]).catch(() => setError(HOME.failed)).finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="page" style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
        <Spinner size={40} />
      </div>
    )
  }

  const grid: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 14 }

  return (
    <div className="page">
      {error && <p className="error-text" style={{ marginBottom: 12 }}>{error}</p>}
      <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div className="card" style={{ flex: '1 1 280px', maxWidth: 380 }}>
          <h2 style={{ fontSize: 18, marginBottom: 16 }}>{BODY_TEXT.title}</h2>
          {body ? (
            <>
              {body.image_url && (
                <img
                  src={body.image_url}
                  alt={BODY_TEXT.imageAlt}
                  style={{
                    width: '100%', maxHeight: 340, objectFit: 'contain', borderRadius: 'var(--radius-md)',
                    background: 'var(--inset)', marginBottom: 12,
                  }}
                />
              )}
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                <StatusChip status={body.confirmed_at ? 'approved' : 'pending'} />
                <StatusChip status="private" />
              </div>
              <p style={{ color: 'var(--text-soft)', fontSize: 13, marginBottom: 12 }}>{BODY_TEXT.lockedNote}</p>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {!body.confirmed_at && <Link to="/body/confirm" className="btn btn-primary btn-sm">{BODY_TEXT.confirm}</Link>}
                <Link to="/profile" style={{ fontSize: 13, color: 'var(--accent)', alignSelf: 'center' }}>{BODY_TEXT.profile}</Link>
              </div>
            </>
          ) : (
            <>
              <p style={{ color: 'var(--muted)', fontSize: 14, marginBottom: 16 }}>{BODY_TEXT.none}</p>
              <Link to="/body/upload" className="btn btn-primary btn-sm">{BODY_TEXT.upload}</Link>
            </>
          )}
        </div>

        <div style={{ flex: '3 1 480px', minWidth: 0 }}>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', marginBottom: 24 }}>
            <div style={{ flex: 1, minWidth: 200 }}>
              <h1 style={{ fontSize: 30, fontWeight: 700, marginBottom: 4 }}>{HOME.hello}</h1>
              <p style={{ color: 'var(--text-soft)' }}>{HOME.lead}</p>
            </div>
            <Link to="/garments/upload" className="btn btn-secondary">{HOME.uploadGarment}</Link>
            <Link to="/tryon" className="btn btn-primary">{HOME.tryOn}</Link>
          </div>

          <Section title={HOME.garments} to="/wardrobe">
            {garments.length === 0 ? (
              <p style={{ color: 'var(--muted)', fontSize: 14 }}>{HOME.noGarments}</p>
            ) : (
              <div style={grid}>
                {garments.slice(0, 4).map((g) => (
                  <Link key={g.id} to={`/garments/${g.id}/landmarks`} className="card" style={{ padding: 12, textDecoration: 'none' }}>
                    <div style={thumb}>
                      {g.image_url ? (
                        <img src={g.image_url} alt={HOME.garmentAlt} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                      ) : (
                        <span style={{ color: 'var(--muted)', fontSize: 12 }}>{HOME.preparing}</span>
                      )}
                    </div>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      <StatusChip status={g.type} />
                      <StatusChip status={g.visibility === 'public' ? g.status : g.visibility} />
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </Section>

          <Section title={HOME.outfits} to="/outfits">
            {outfits.filter((o) => o.result_url).length === 0 ? (
              <p style={{ color: 'var(--muted)', fontSize: 14 }}>{HOME.noOutfits}</p>
            ) : (
              <div style={grid}>
                {outfits.filter((o) => o.result_url).slice(0, 4).map((o) => (
                  <Link key={o.id} to="/outfits" className="card" style={{ padding: 12 }}>
                    <div style={{ ...thumb, height: 220, marginBottom: 0 }}>
                      <img src={o.result_url ?? ''} alt={HOME.outfitAlt} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </Section>
        </div>
      </div>
    </div>
  )
}
