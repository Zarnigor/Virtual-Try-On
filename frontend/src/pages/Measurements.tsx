import { useState, useEffect, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { getBody, updateMeasurements, type Body } from '../api/bodies'
import type { Measurements as MeasurementsT } from '../api/types'
import Spinner from '../components/Spinner'
import { FIT_MEASUREMENT_FIELDS, changedKeys, validateFitMeasurements } from '../fit/measurementFields'
import { parseCm } from '../fit/sizeFields'
import { BODY_SIZE_LABELS, FIT_TEXT, MEASUREMENTS_TEXT as T } from '../locale/uz'

type Key = keyof MeasurementsT

/** shoulder / chest / waist / hip = circumferences; shoulder_width = a width; inseam = length (docs/11). */
const FIELDS: Array<{ key: Key; example: number }> = [
  { key: 'chest', example: 94 },
  { key: 'waist', example: 78 },
  { key: 'hip', example: 100 },
  { key: 'shoulder_width', example: 44 },
  { key: 'inseam', example: 80 },
  { key: 'shoulder', example: 112 },
]
const RANGE = Object.fromEntries(FIT_MEASUREMENT_FIELDS.map((f) => [f.key, f])) as Record<string, { min: number; max: number }>

export default function Measurements() {
  const navigate = useNavigate()
  const [body, setBody] = useState<Body | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<Key | 'height_cm', string>>>({})

  const [height, setHeight] = useState('')
  const [values, setValues] = useState<Partial<Record<Key, string>>>({})

  const fill = (data: Body) => {
    setBody(data)
    setHeight(data.height_cm != null ? String(data.height_cm) : '')
    const m = data.measurements ?? {}
    setValues(Object.fromEntries(FIELDS.map((f) => [f.key, m[f.key] != null ? String(m[f.key]) : ''])))
  }

  useEffect(() => {
    getBody().then(({ data }) => fill(data)).catch(() => {}).finally(() => setLoading(false))
  }, [])

  const validate = () => {
    const { shoulder, ...fit } = values
    const errs: typeof fieldErrors = { ...validateFitMeasurements({ ...fit, height_cm: height }, false).errors }
    const s = parseCm(shoulder)
    if (s !== null && (Number.isNaN(s) || s <= 0)) errs.shoulder = T.positive(BODY_SIZE_LABELS.shoulder)
    return errs
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setNotice('')
    const errs = validate()
    setFieldErrors(errs)
    if (Object.keys(errs).length > 0 || !body) return
    const changes = changedKeys({ height_cm: body.height_cm, measurements: body.measurements },
      { height_cm: height, measurements: values })
    if (Object.keys(changes).length === 0) {
      setNotice(T.noChange)
      return
    }
    setSaving(true)
    try {
      const { data } = await updateMeasurements(changes)  // merge: only the changed keys (docs/09 #127)
      fill(data)
      setNotice(T.saved)
      setTimeout(() => navigate('/'), 1200)
    } catch (err: unknown) {
      const data = (err as { response?: { data?: Record<string, unknown> } })?.response?.data
      const detail = typeof data?.detail === 'string' ? data.detail : undefined
      const first = data ? Object.values(data).flat().find((v) => typeof v === 'string') : undefined
      setError(detail || (first as string | undefined) || T.saveError)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="page" style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
        <Spinner size={40} />
      </div>
    )
  }

  const locked = body !== null && !body.can_change_measurements
  const input = (id: Key | 'height_cm', value: string, onChange: (v: string) => void, example: number) => {
    const r = RANGE[id]
    return (
      <div className="field" key={id}>
        <label className="label" htmlFor={id}>{BODY_SIZE_LABELS[id]} ({FIT_TEXT.cm})</label>
        <input id={id} className="input" type="number" inputMode="decimal" step="0.1" min={r?.min ?? 1} max={r?.max}
          value={value} onChange={(e) => onChange(e.target.value)} disabled={locked}
          placeholder={r ? `${r.min}–${r.max}` : T.placeholder(example)} aria-invalid={fieldErrors[id] ? true : undefined} />
        {fieldErrors[id] && <p className="error-text" style={{ marginTop: 4 }}>{fieldErrors[id]}</p>}
      </div>
    )
  }

  return (
    <div className="page" style={{ maxWidth: 520 }}>
      <h1 className="page-title">{T.title}</h1>

      {locked && (
        <div className="banner banner-warning" role="status" style={{ marginBottom: 20 }}>
          {T.locked}
          {body?.measurements_unlock_at &&
            T.nextChange(new Date(body.measurements_unlock_at).toLocaleDateString('uz-UZ'))}
        </div>
      )}

      <div className="card">
        <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 8 }}>{T.help}</p>
        <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 8 }}>{T.fitHelp}</p>
        {!locked && <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 20 }}>{T.lockWarning} {FIT_TEXT.bodyNotChangeable}</p>}

        <form onSubmit={handleSubmit}>
          {input('height_cm', height, setHeight, 175)}
          {FIELDS.map((f) => input(f.key, values[f.key] ?? '', (v) => setValues((s) => ({ ...s, [f.key]: v })), f.example))}

          {error && <p className="error-text" role="alert" style={{ marginBottom: 12 }}>{error}</p>}
          {notice && <p style={{ color: 'var(--accent)', fontSize: 13, marginBottom: 12 }}>{notice}</p>}

          <div style={{ display: 'flex', gap: 12 }}>
            <button type="submit" className="btn btn-primary" disabled={saving || locked} style={{ flex: 1 }}>
              {saving ? T.saving : T.save}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => navigate('/')}>
              {T.back}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
