import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getBody, confirmBody, deleteBody, type Body } from '../api/bodies'
import type { BodyLandmarks } from '../api/types'
import Spinner from '../components/Spinner'
import LandmarkEditor from '../components/landmark-editor/LandmarkEditor'
import { BODY_GROUPS, BODY_RULES } from '../components/landmark-editor/bodyGroups'
import { CONFIRM_FIELDS, confirmSizes, shoulderWidthCm } from '../fit/bodySizes'
import type { MeasurementValues } from '../fit/measurementFields'
import { parseCm } from '../fit/sizeFields'
import { BODY_CONFIRM_TEXT as T, BODY_SIZE_LABELS, FIT_TEXT } from '../locale/uz'

/** Two steps (docs/09 #130): 1 = landmarks (editor), 2 = sizes (required ones marked), then POST body/confirm/. */
export default function BodyConfirm() {
  const navigate = useNavigate()
  const [body, setBody] = useState<Body | null>(null)
  const [loading, setLoading] = useState(true)
  const [step, setStep] = useState<1 | 2>(1)
  const [landmarks, setLandmarks] = useState<Record<string, unknown> | null>(null)
  const [values, setValues] = useState<MeasurementValues>({})
  // false = the shoulder width shown is the estimate: it is not sent and the backend computes the same value
  const [shoulderTouched, setShoulderTouched] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<string, string>>>({})
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getBody()
      .then(({ data }) => setBody(data))
      .catch(() => setBody(null))
      .finally(() => setLoading(false))
  }, [])

  const height = parseCm(values.height_cm)
  const estimate = landmarks && height !== null && !Number.isNaN(height) ? shoulderWidthCm(landmarks, height) : null
  const shown: MeasurementValues = shoulderTouched
    ? values
    : { ...values, shoulder_width: estimate !== null ? String(estimate) : '' }

  const toSizes = (lm: Record<string, unknown>) => {
    setLandmarks(lm)
    setStep(2)
    setError('')
  }

  const setField = (key: keyof MeasurementValues, raw: string) => {
    if (key === 'shoulder_width') setShoulderTouched(true)
    setValues((prev) => ({ ...(key === 'shoulder_width' ? shown : prev), [key]: raw }))
  }

  const handleConfirm = async () => {
    if (!body || !landmarks) return
    const sizes = confirmSizes(shown, shoulderTouched)
    setFieldErrors(sizes.errors)
    if (!sizes.ok) {
      setError(T.fixFields)
      return
    }
    if (!confirm(T.confirmQuestion)) return
    setConfirming(true)
    setError('')
    try {
      await confirmBody({ landmarks: landmarks as unknown as BodyLandmarks, ...sizes.request })
      navigate('/tryon')
    } catch (err: unknown) {
      const data = (err as { response?: { data?: { code?: string; detail?: string; field?: string } } })?.response?.data
      if (data?.code === 'LANDMARKS_INVALID') {
        setStep(1)  // the points are wrong: back to the editor
        setError(data.detail ?? T.error)
      } else if (data?.code === 'MEASUREMENTS_INVALID' && data.field) {
        setFieldErrors({ [data.field]: data.detail })
        setError(data.detail ?? T.error)
      } else {
        setError(data?.detail || T.error)
      }
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

  if (body.confirmed_at) {
    return (
      <div className="page">
        <p style={{ color: 'var(--muted)' }}>Tana allaqachon tasdiqlangan. <a href="/tryon">Kiyib koʻrish</a></p>
      </div>
    )
  }

  if (step === 2) {
    return (
      <div className="page" style={{ maxWidth: 560 }}>
        <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 4 }}>{T.step2}</p>
        <h1 className="page-title">{T.sizesTitle}</h1>
        <div className="card">
          <p style={{ fontSize: 13, color: 'var(--text-soft)', marginBottom: 12 }}>{T.sizesHelp}</p>
          {CONFIRM_FIELDS.map((f) => (
            <div className="field" key={f.key} style={{ marginBottom: 10 }}>
              <label className="label" htmlFor={`confirm-${f.key}`}>
                {BODY_SIZE_LABELS[f.key]} ({FIT_TEXT.cm})
                {f.required
                  ? <span style={{ color: 'var(--danger)' }} title={FIT_TEXT.requiredMark}> *</span>
                  : <span style={{ color: 'var(--muted)', fontWeight: 400 }}> ({FIT_TEXT.optional})</span>}
                {f.key === 'shoulder_width' && !shoulderTouched && estimate !== null && (
                  <span style={{ color: 'var(--warning)', fontWeight: 400 }}> — {T.estimated}</span>
                )}
              </label>
              <input id={`confirm-${f.key}`} className="input" type="number" inputMode="decimal" step="0.1"
                min={f.min} max={f.max} placeholder={`${f.min}–${f.max}`} value={shown[f.key] ?? ''}
                aria-invalid={fieldErrors[f.key] ? true : undefined}
                onChange={(e) => setField(f.key, e.target.value)} />
              {f.key === 'shoulder_width' && !shoulderTouched && (
                <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                  {estimate !== null ? T.estimatedHelp : T.needHeight}
                </p>
              )}
              {fieldErrors[f.key] && <p className="error-text" style={{ marginTop: 4 }}>{fieldErrors[f.key]}</p>}
            </div>
          ))}
          <p style={{ fontSize: 12, color: 'var(--muted)', margin: '12px 0' }}>{T.lockNote}</p>
          {error && <p className="error-text" role="alert" style={{ marginBottom: 12 }}>{error}</p>}
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn btn-secondary" onClick={() => { setStep(1); setError('') }} disabled={confirming}>
              {T.back}
            </button>
            <button className="btn btn-primary" onClick={handleConfirm} disabled={confirming}>
              {confirming ? T.confirming : T.confirm}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <button className="btn btn-secondary btn-sm" onClick={handleReupload}>Boshqa rasm yuklash</button>
        <p style={{ color: 'var(--text-soft)', fontSize: 14, margin: 0 }}>
          Nuqtalar avtomatik qoʻyildi. Tekshiring, kerak boʻlsa suring. Keyingi qadamda oʻlchamlaringizni kiritasiz.
        </p>
      </div>
      {error && <p className="error-text" style={{ marginBottom: 12 }}>{error}</p>}
      {body.image_url ? (
        <LandmarkEditor
          imageUrl={body.image_url}
          imageAlt="Tana rasmi"
          bounds={{ w: 600, h: 1200 }}
          groups={BODY_GROUPS}
          rules={BODY_RULES}
          landmarks={landmarks ?? body.landmarks}
          heading="Tana nuqtalari"
          subheading="Har bir chiziqning chap va oʻng nuqtasini tana chetiga qoʻying."
          saveLabel={T.next}
          stepLabel={T.step1}
          onSave={toSizes}
        />
      ) : (
        <p className="error-text">Tana rasmi yoʻq. Qayta yuklang.</p>
      )}
    </div>
  )
}
