import { useEffect, useState } from 'react'
import { listAvatars, type Avatar } from '../api/avatars'
import { listGarments, type Garment } from '../api/garments'
import { startTryon } from '../api/tryon'
import { getOutfit } from '../api/outfits'
import { usePoll } from '../components/usePoll'
import Spinner from '../components/Spinner'
import DevAiWarning from '../components/DevAiWarning'
import StatusChip from '../components/StatusChip'

export default function TryOn() {
  const [base, setBase] = useState<'body' | 'avatar'>('body')
  const [avatars, setAvatars] = useState<Avatar[]>([])
  const [selectedAvatar, setSelectedAvatar] = useState<number | null>(null)
  const [garments, setGarments] = useState<Garment[]>([])
  const [selectedGarments, setSelectedGarments] = useState<number[]>([])
  const [jobId, setJobId] = useState<number | null>(null)
  const [outfitId, setOutfitId] = useState<number | null>(null)
  const [resultUrl, setResultUrl] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)

  const { job } = usePoll(jobId)

  useEffect(() => {
    listAvatars().then(({ data }) => setAvatars(data)).catch(() => {})
    listGarments('mine').then(({ data }) => setGarments(data)).catch(() => {})
  }, [])

  useEffect(() => {
    if (job?.status === 'done' && outfitId) {
      getOutfit(outfitId)
        .then(({ data }) => setResultUrl(data.result_url))
        .catch(() => {})
    }
  }, [job, outfitId])

  const toggleGarment = (id: number, type: string) => {
    setSelectedGarments((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      // remove any existing garment of same type
      const filtered = prev.filter((gid) => {
        const g = garments.find((x) => x.id === gid)
        return g?.type !== type
      })
      return [...filtered, id]
    })
  }

  const handleStart = async () => {
    if (selectedGarments.length === 0) {
      setError('Kamida bitta kiyim tanlang')
      return
    }
    if (base === 'avatar' && !selectedAvatar) {
      setError('Avatar tanlang')
      return
    }
    setError('')
    setStarting(true)
    setJobId(null)
    setResultUrl(null)
    try {
      const { data } = await startTryon({
        base,
        avatar_id: base === 'avatar' ? (selectedAvatar ?? undefined) : undefined,
        garment_ids: selectedGarments,
      })
      setJobId(data.job_id)
      setOutfitId(data.outfit_id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Xato yuz berdi')
    } finally {
      setStarting(false)
    }
  }

  const isPolling = jobId !== null && job?.status !== 'done' && job?.status !== 'failed'

  return (
    <div className="page">
      <h1 className="page-title">Sinab koʻrish</h1>

      <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: 24, alignItems: 'start' }}>
        {/* Left: controls */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Base selector */}
          <div className="card">
            <h2 style={{ fontSize: 16, marginBottom: 12 }}>Asos</h2>
            <div style={{ display: 'flex', gap: 10, marginBottom: base === 'avatar' ? 16 : 0 }}>
              {(['body', 'avatar'] as const).map((b) => (
                <label
                  key={b}
                  style={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    minHeight: 44,
                    border: `1px solid ${base === b ? 'var(--accent)' : 'var(--border-strong)'}`,
                    borderRadius: 'var(--radius-sm)',
                    background: base === b ? 'var(--accent-soft)' : 'var(--inset)',
                    cursor: 'pointer',
                    color: base === b ? 'var(--accent)' : 'var(--text-soft)',
                    fontSize: 14,
                    fontWeight: 500,
                    transition: 'all 0.15s',
                  }}
                >
                  <input
                    type="radio"
                    name="base"
                    value={b}
                    checked={base === b}
                    onChange={() => setBase(b)}
                    style={{ display: 'none' }}
                  />
                  {b === 'body' ? '🧍 Mening tanam' : '🤖 Avatar'}
                </label>
              ))}
            </div>

            {base === 'avatar' && (
              <div>
                <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>Avatar tanlang</p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 200, overflowY: 'auto' }}>
                  {avatars.length === 0 ? (
                    <p style={{ color: 'var(--muted)', fontSize: 13 }}>Avatarlar topilmadi</p>
                  ) : (
                    avatars.map((av) => (
                      <label
                        key={av.id}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 10,
                          padding: '8px 12px',
                          borderRadius: 'var(--radius-sm)',
                          border: `1px solid ${selectedAvatar === av.id ? 'var(--accent)' : 'var(--border)'}`,
                          background: selectedAvatar === av.id ? 'var(--accent-soft)' : 'var(--inset)',
                          cursor: 'pointer',
                        }}
                      >
                        <input
                          type="radio"
                          name="avatar"
                          checked={selectedAvatar === av.id}
                          onChange={() => setSelectedAvatar(av.id)}
                          style={{ display: 'none' }}
                        />
                        {av.image_url && (
                          <img
                            src={av.image_url}
                            alt="Avatar"
                            style={{ width: 36, height: 72, objectFit: 'contain', borderRadius: 4 }}
                          />
                        )}
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 500 }}>
                            {av.sex === 'male' ? 'Erkak' : 'Ayol'} — {av.build}
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--muted)' }}>ID {av.id}</div>
                        </div>
                      </label>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Garment picker */}
          <div className="card">
            <h2 style={{ fontSize: 16, marginBottom: 12 }}>Kiyimlar</h2>
            {garments.length === 0 ? (
              <p style={{ color: 'var(--muted)', fontSize: 13 }}>
                Hali kiyim yuklanmagan.{' '}
                <a href="/garments/upload">Yuklash</a>
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {garments.map((g) => {
                  const isSelected = selectedGarments.includes(g.id)
                  const hasLandmarks = g.landmarks && Object.keys(g.landmarks).length > 0
                  return (
                    <label
                      key={g.id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 10,
                        padding: '8px 12px',
                        borderRadius: 'var(--radius-sm)',
                        border: `1px solid ${isSelected ? 'var(--accent)' : 'var(--border)'}`,
                        background: isSelected ? 'var(--accent-soft)' : 'var(--inset)',
                        cursor: hasLandmarks ? 'pointer' : 'not-allowed',
                        opacity: hasLandmarks ? 1 : 0.5,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        disabled={!hasLandmarks}
                        onChange={() => hasLandmarks && toggleGarment(g.id, g.type)}
                        style={{ accentColor: 'var(--accent)' }}
                      />
                      {g.image_url && (
                        <img
                          src={g.image_url}
                          alt="Kiyim"
                          style={{ width: 32, height: 48, objectFit: 'contain', borderRadius: 4 }}
                        />
                      )}
                      <div style={{ flex: 1 }}>
                        {g.ai_skipped && <DevAiWarning compact />}
                        <StatusChip status={g.type} />
                        {!hasLandmarks && (
                          <span style={{ fontSize: 11, color: 'var(--warning)', marginLeft: 6 }}>
                            Belgilar kerak
                          </span>
                        )}
                      </div>
                    </label>
                  )
                })}
              </div>
            )}
          </div>

          {error && <p className="error-text">{error}</p>}

          <button
            className="btn btn-primary"
            onClick={handleStart}
            disabled={starting || isPolling}
            style={{ width: '100%' }}
          >
            {starting || isPolling ? 'Qayta ishlanmoqda…' : '✨ Sinab koʻrish'}
          </button>
        </div>

        {/* Right: result */}
        <div className="card" style={{ minHeight: 400, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          {!jobId && !resultUrl && (
            <div style={{ textAlign: 'center', color: 'var(--muted)' }}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>👕</div>
              <p>Kiyim va asos tanlab, "Sinab koʻrish" tugmasini bosing</p>
            </div>
          )}

          {isPolling && (
            <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
              <Spinner size={48} />
              <p style={{ color: 'var(--muted)' }}>
                {job?.status === 'running' ? 'Kiyim kiydirilmoqda…' : 'Navbatda kutilmoqda…'}
              </p>
            </div>
          )}

          {job?.status === 'failed' && (
            <div style={{ textAlign: 'center', color: 'var(--danger)' }}>
              <div style={{ fontSize: 40, marginBottom: 8 }}>❌</div>
              <p>{job.error_message || 'Xato yuz berdi'}</p>
            </div>
          )}

          {resultUrl && (
            <div style={{ width: '100%' }}>
              <img
                src={resultUrl}
                alt="Natija"
                style={{
                  width: '100%',
                  maxHeight: 700,
                  objectFit: 'contain',
                  borderRadius: 'var(--radius-md)',
                  background: 'var(--inset)',
                }}
              />
              <div style={{ marginTop: 16, display: 'flex', gap: 10 }}>
                <a
                  href={resultUrl}
                  download="tryon-result.png"
                  className="btn btn-secondary btn-sm"
                >
                  ⬇ Yuklab olish
                </a>
                <a href="/outfits" className="btn btn-secondary btn-sm">
                  Koʻrinishlarga oʻtish
                </a>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
