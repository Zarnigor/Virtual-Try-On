import { useEffect, useRef, useState } from 'react'
import { listAvatars, type Avatar } from '../api/avatars'
import { garmentFitsSex, listGarments, type Garment } from '../api/garments'
import { getBody, setBodySex, type Body } from '../api/bodies'
import { getConfig } from '../api/config'
import { fitCheck, startTryon } from '../api/tryon'
import { getOutfit } from '../api/outfits'
import { usePoll } from '../components/usePoll'
import Spinner from '../components/Spinner'
import DevAiWarning from '../components/DevAiWarning'
import StatusChip from '../components/StatusChip'
import { GenderBadge, Segmented } from '../components/GarmentSettingsPanel'
import FitNotice, { FitLines, type FitAnswer } from '../components/FitNotice'
import type { FitZoneCheck, Sex } from '../api/types'
import { fitWarningBlocks } from '../fit/fitNotice'
import { Link } from 'react-router-dom'
import { FIT_TEXT, GARMENT_TYPE_NAMES, SEX_LABELS, TRYON_BODY, TRYON_GENDER, TRYON_QUALITY } from '../locale/uz'

const FIT_CODES = ['GARMENT_SIZE_MISSING', 'BODY_SIZE_MISSING', 'SIZE_MISMATCH']
const FIT_DEBOUNCE_MS = 400

const TRYON_ERRORS: Record<string, string> = {
  GENDER_MISMATCH: TRYON_GENDER.mismatch,
  BODY_SEX_REQUIRED: TRYON_GENDER.bodySexRequired,
}

export default function TryOn() {
  const [base, setBase] = useState<'body' | 'avatar'>('avatar')
  // The user picked a base by hand: the confirmed-body default must not override it when getBody answers late.
  const baseTouched = useRef(false)
  // 400 BODY_NOT_CONFIRMED (docs/09 #130): its detail, shown with a link to the confirm page
  const [notConfirmedDetail, setNotConfirmedDetail] = useState('')
  const [avatars, setAvatars] = useState<Avatar[]>([])
  const [selectedAvatar, setSelectedAvatar] = useState<number | null>(null)
  // Model (avatar) path: gender only (docs/09 #124). Choosing a gender selects that sex's "average" avatar.
  const [avSex, setAvSex] = useState<Sex | ''>('')
  const [avError, setAvError] = useState('')
  const [garments, setGarments] = useState<Garment[]>([])
  const [scope, setScope] = useState<'all' | 'mine' | null>(null)
  // docs/09 #97: the list shows only garments for the base's sex (+ unisex) unless "show all" is on
  const [showAll, setShowAll] = useState(false)
  const [body, setBody] = useState<Body | null>(null)
  const [selectedGarments, setSelectedGarments] = useState<number[]>([])
  const [jobId, setJobId] = useState<number | null>(null)
  const [outfitId, setOutfitId] = useState<number | null>(null)
  const [resultUrl, setResultUrl] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)
  // The garments of the last started try-on (names for the fit_warnings notice).
  const [triedIds, setTriedIds] = useState<number[]>([])
  // Fit check (docs/11). The flag only decides whether a non-fitting garment blocks the button; results always show.
  const [fitEnabled, setFitEnabled] = useState(false)
  const [fitAnswers, setFitAnswers] = useState<Record<number, FitAnswer>>({})
  const [fitError, setFitError] = useState('')
  const [checking, setChecking] = useState(false)
  const fitSeq = useRef(0)

  const { job } = usePoll(jobId)

  useEffect(() => {
    listAvatars().then(({ data }) => setAvatars(data)).catch(() => {})
    // Demo mode also lists the catalog (the demo garments); otherwise only the user's own garments, as before.
    getConfig()
      .then((c) => { setScope(c.demo_mode ? 'all' : 'mine'); setFitEnabled(c.fit_check_enabled) })
      .catch(() => setScope('mine'))
    // The own body is the main path (docs/09 #130): a confirmed body is the default base; avatars stay selectable.
    getBody()
      .then(({ data }) => {
        setBody(data)
        if (data.confirmed_at && !baseTouched.current) setBase('body')
      })
      .catch(() => setBody(null))
  }, [])

  useEffect(() => {
    if (base !== 'body') return
    getBody().then(({ data }) => setBody(data)).catch(() => setBody(null))
  }, [base])
  const bodyUnconfirmed = base === 'body' && body !== null && !body.confirmed_at

  const baseSex: Sex | null =
    base === 'avatar' ? (avatars.find((a) => a.id === selectedAvatar)?.sex ?? null) : (body?.sex ?? null)
  const mismatched = (g: Garment) => baseSex !== null && !garmentFitsSex(g.gender, baseSex)

  useEffect(() => {
    if (!scope) return
    listGarments(scope, undefined, undefined, showAll || !baseSex ? 'all' : baseSex)
      .then(({ data }) => {
        setGarments(data)
        setSelectedGarments((prev) => prev.filter((id) => data.some((g) => g.id === id)))
      })
      .catch(() => {})
  }, [scope, baseSex, showAll])

  // GET tryon/fit-check/ whenever the base or the selection changes (debounced; stale answers dropped).
  const garmentKey = selectedGarments.join(',')
  const bodyReady = body !== null && body.confirmed_at !== null
  useEffect(() => {
    const seq = ++fitSeq.current
    const ready = selectedGarments.length > 0 && (base === 'avatar' ? selectedAvatar !== null : bodyReady)
    if (!ready) {
      setFitAnswers({})
      setFitError('')
      setChecking(false)
      return
    }
    setChecking(true)
    const timer = setTimeout(() => {
      fitCheck(base, selectedGarments, selectedAvatar ?? undefined)
        .then(({ data }) => {
          if (seq !== fitSeq.current) return
          setFitAnswers(Object.fromEntries(data.results.map((r) => [r.garment_id, {
            garmentId: r.garment_id, fits: r.fits, checks: r.checks, warnings: r.warnings ?? [], code: r.code,
          }])))
          setFitError('')
        })
        .catch((err: unknown) => {
          if (seq !== fitSeq.current) return
          const data = (err as { response?: { data?: { code?: string; detail?: string } } })?.response?.data
          setFitAnswers({})
          setFitError(data?.code === 'BODY_NOT_CONFIRMED' ? '' : (data?.detail ?? ''))  // shown with its link below
          if (data?.code === 'BODY_NOT_CONFIRMED') setNotConfirmedDetail(data.detail ?? TRYON_BODY.notConfirmed)
        })
        .finally(() => { if (seq === fitSeq.current) setChecking(false) })
    }, FIT_DEBOUNCE_MS)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, selectedAvatar, garmentKey, bodyReady])

  const notFitting = selectedGarments.filter((id) => fitAnswers[id] && !fitAnswers[id].fits)
  const fitBlocked = fitEnabled && notFitting.length > 0

  const chooseAvatarSex = (sex: Sex) => {
    setAvSex(sex)
    const ofSex = avatars.filter((a) => a.sex === sex)
    const pick = ofSex.find((a) => a.build === 'average') ?? ofSex[0]
    setSelectedAvatar(pick ? pick.id : null)
    setAvError(pick ? '' : 'Bu jins uchun model topilmadi.')
  }

  const chooseBodySex = (sex: Sex) => {
    setBodySex(sex).then(({ data }) => setBody(data)).catch(() => setError(TRYON_GENDER.bodySexRequired))
  }

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
    if (base === 'body' && body && !body.sex) {
      setError(TRYON_GENDER.bodySexRequired)
      return
    }
    if (garments.some((g) => selectedGarments.includes(g.id) && mismatched(g))) {
      setError(TRYON_GENDER.mismatch)  // the backend refuses it too (400 GENDER_MISMATCH)
      return
    }
    if (fitBlocked) return  // the button is disabled too; the backend refuses it as well (flag on)
    setError('')
    setNotConfirmedDetail('')
    setStarting(true)
    setJobId(null)
    setResultUrl(null)
    try {
      const { data } = await startTryon({
        base,
        avatar_id: base === 'avatar' ? (selectedAvatar ?? undefined) : undefined,
        garment_ids: selectedGarments,
      })
      setTriedIds(selectedGarments)
      setJobId(data.job_id)
      setOutfitId(data.outfit_id)
    } catch (err: unknown) {
      const data = (err as { response?: { data?: {
        code?: string; detail?: string; garment_id?: number; checks?: FitZoneCheck[]
      } } })?.response?.data
      if (data?.code && FIT_CODES.includes(data.code)) {
        // Race (garment sizes changed after the last fit-check) with the flag on: show it like a fit-check result.
        const code = data.code === 'SIZE_MISMATCH' ? undefined : data.code as FitAnswer['code']
        const ids = data.code === 'BODY_SIZE_MISSING' ? selectedGarments : [data.garment_id ?? -1]
        setFitAnswers((prev) => ({
          ...prev,
          ...Object.fromEntries(ids.map((id) => [id, { garmentId: id, fits: false, checks: data.checks ?? [], warnings: [], code }])),
        }))
      }
      // base=avatar: the backend detail asks the user to enter their sizes, which they cannot do for an avatar.
      const avatarSizes = base === 'avatar' && data?.code === 'BODY_SIZE_MISSING'
      if (data?.code === 'BODY_NOT_CONFIRMED') {
        setNotConfirmedDetail(data.detail || TRYON_BODY.notConfirmed)
        return
      }
      setError((avatarSizes && FIT_TEXT.avatarSizeMissing)
        || (data?.code && TRYON_ERRORS[data.code]) || data?.detail || 'Xato yuz berdi')
    } finally {
      setStarting(false)
    }
  }

  const isPolling = jobId !== null && job?.status !== 'done' && job?.status !== 'failed'
  const garmentName = (id: number) => {
    const g = garments.find((x) => x.id === id)
    return g ? (g.name || GARMENT_TYPE_NAMES[g.type]) : `#${id}`
  }
  // Job result fit_warnings (docs/09 #128): rendered, but big; the garment name only when several were tried on.
  const fitWarnings = fitWarningBlocks(job?.result, triedIds.length, garmentName)

  return (
    <div className="page">
      <h1 className="page-title">Kiyib koʻrish</h1>

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
                    onChange={() => { baseTouched.current = true; setBase(b); setNotConfirmedDetail('') }}
                    style={{ display: 'none' }}
                  />
                  {b === 'body' ? 'Mening tanam' : 'Model'}
                </label>
              ))}
            </div>

            {base === 'body' && body && !body.sex && (
              <div style={{ marginTop: 16 }}>
                <Segmented<Sex> title={TRYON_GENDER.bodySexTitle} value="" options={SEX_LABELS} onChange={chooseBodySex} />
                <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>{TRYON_GENDER.bodySexHelp}</p>
              </div>
            )}

            {base === 'avatar' && (
              <div>
                <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
                  Jinsni tanlang: shu jinsdagi model tanlanadi.
                </p>
                <Segmented<Sex> title="Jins" value={avSex} options={SEX_LABELS} onChange={chooseAvatarSex} />
                {avError && <p className="error-text" role="alert" style={{ marginTop: 8 }}>{avError}</p>}
                {avSex && !avError && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 260, overflowY: 'auto', marginTop: 12 }}>
                    {avatars.filter((av) => av.sex === avSex).map((av) => (
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
                          <img src={av.image_url} alt="Model" style={{ width: 36, height: 72, objectFit: 'contain', borderRadius: 4 }} />
                        )}
                        <div style={{ fontSize: 13, fontWeight: 500 }}>
                          {av.sex === 'male' ? 'Erkak' : 'Ayol'} — {av.build}
                        </div>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Garment picker */}
          <div className="card">
            <h2 style={{ fontSize: 16, marginBottom: 12 }}>Kiyimlar</h2>
            <div style={{ marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <p style={{ fontSize: 12, color: 'var(--muted)' }}>
                {baseSex ? TRYON_GENDER.filteredFor(SEX_LABELS[baseSex]) : TRYON_GENDER.pickBaseFirst}
              </p>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)}
                  style={{ accentColor: 'var(--accent)' }} />
                {TRYON_GENDER.showAll}
              </label>
            </div>
            {garments.length === 0 && baseSex && !showAll ? (
              <p style={{ color: 'var(--muted)', fontSize: 13 }}>{TRYON_GENDER.noMatching}</p>
            ) : garments.length === 0 ? (
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
                        <StatusChip status={g.type} />{' '}
                        <GenderBadge gender={g.gender} />
                        {mismatched(g) && (
                          <span className="gender-badge" data-mismatch="true" style={{ marginLeft: 6, color: 'var(--warning)' }}>
                            {TRYON_GENDER.otherGender}
                          </span>
                        )}
                        {!hasLandmarks && (
                          <span style={{ fontSize: 11, color: 'var(--warning)', marginLeft: 6 }}>
                            Belgilar kerak
                          </span>
                        )}
                        {g.owned_by_me && !g.sizes_complete && (
                          <span style={{ fontSize: 11, color: 'var(--warning)', marginLeft: 6 }}>
                            {FIT_TEXT.sizesMissingBadge}
                          </span>
                        )}
                        {isSelected && fitAnswers[g.id] && (
                          <FitNotice answer={fitAnswers[g.id]} base={base} ownGarment={g.owned_by_me} />
                        )}
                      </div>
                    </label>
                  )
                })}
              </div>
            )}
          </div>

          {checking && <p style={{ fontSize: 12, color: 'var(--muted)' }}>{FIT_TEXT.checking}</p>}
          {fitError && <p className="error-text" role="alert">{fitError}</p>}
          {!fitEnabled && notFitting.length > 0 && (
            <p style={{ fontSize: 12, color: 'var(--muted)' }}>{FIT_TEXT.fitInfoOnly}</p>
          )}
          {error && <p className="error-text" role="alert">{error}</p>}
          {(notConfirmedDetail || bodyUnconfirmed) && (
            <p className="error-text" role="alert">
              {notConfirmedDetail || TRYON_BODY.notConfirmed}{' '}
              <Link to="/body/confirm">{TRYON_BODY.confirmLink}</Link>
            </p>
          )}

          <button
            className="btn btn-primary"
            onClick={handleStart}
            disabled={starting || isPolling || fitBlocked}
            style={{ width: '100%' }}
          >
            {starting || isPolling ? 'Qayta ishlanmoqda…' : 'Kiyib koʻrish'}
          </button>
        </div>

        {/* Right: result */}
        <div className="card" style={{ minHeight: 400, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          {!jobId && !resultUrl && (
            <div style={{ textAlign: 'center', color: 'var(--muted)' }}>
              <p>Kiyim va asos tanlab, "Kiyib koʻrish" tugmasini bosing</p>
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
              <p>{job.error_message || 'Xato yuz berdi'}</p>
            </div>
          )}

          {resultUrl && (
            <div style={{ width: '100%' }}>
              {job?.result?.demo === true && (
                <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 8 }}>
                  <strong>DEMO:</strong> bu natija oldindan tayyorlangan (demo rejimi).
                </p>
              )}
              {qualityMessages(job?.result).length > 0 && (
                <ul className="banner banner-warning" role="status" style={{ marginBottom: 8 }}>
                  {qualityMessages(job?.result).map((m) => <li key={m}>{m}</li>)}
                </ul>
              )}
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
              {fitWarnings.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
                  {fitWarnings.map((w) => <FitLines key={w.garmentId} kind="yellow" title={w.title} lines={w.lines} />)}
                </div>
              )}
              <div style={{ marginTop: 16, display: 'flex', gap: 10 }}>
                <a
                  href={resultUrl}
                  download="tryon-result.png"
                  className="btn btn-secondary btn-sm"
                >
                  Yuklab olish
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

/** Known quality warnings of the job result as Uzbek messages (unknown codes are debug only, not shown). */
function qualityMessages(result: Record<string, unknown> | null | undefined): string[] {
  const codes = Array.isArray(result?.quality_warnings) ? (result.quality_warnings as unknown[]) : []
  return codes.filter((c): c is string => typeof c === 'string' && c in TRYON_QUALITY).map((c) => TRYON_QUALITY[c])
}
