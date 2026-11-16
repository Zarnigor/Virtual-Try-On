import { useState, useEffect, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { getBody, updateMeasurements, type Body } from '../api/bodies'
import type { Measurements as MeasurementsT } from '../api/types'
import Spinner from '../components/Spinner'

type Key = keyof MeasurementsT

const FIELDS: Array<{ key: Key; label: string; placeholder: string }> = [
  { key: 'shoulder', label: 'Yelka aylanasi (sm)', placeholder: 'masalan: 112' },
  { key: 'chest', label: 'Koʻkrak aylanasi (sm)', placeholder: 'masalan: 94' },
  { key: 'waist', label: 'Bel aylanasi (sm)', placeholder: 'masalan: 78' },
  { key: 'hip', label: 'Son aylanasi (sm)', placeholder: 'masalan: 100' },
]

export default function Measurements() {
  const navigate = useNavigate()
  const [body, setBody] = useState<Body | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const [height, setHeight] = useState('')
  const [values, setValues] = useState<Record<Key, string>>({ shoulder: '', chest: '', waist: '', hip: '' })

  useEffect(() => {
    getBody()
      .then(({ data }) => {
        setBody(data)
        setHeight(data.height_cm != null ? String(data.height_cm) : '')
        const m = data.measurements ?? {}
        setValues({
          shoulder: m.shoulder != null ? String(m.shoulder) : '',
          chest: m.chest != null ? String(m.chest) : '',
          waist: m.waist != null ? String(m.waist) : '',
          hip: m.hip != null ? String(m.hip) : '',
        })
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    setSuccess(false)
    const measurements: MeasurementsT = {}
    for (const f of FIELDS) {
      if (values[f.key]) measurements[f.key] = Number(values[f.key])
    }
    try {
      await updateMeasurements({
        height_cm: height ? Number(height) : null,
        measurements,
      })
      setSuccess(true)
      setTimeout(() => navigate('/'), 1200)
    } catch (err: unknown) {
      const data = (err as { response?: { data?: Record<string, unknown> } })?.response?.data
      const detail = typeof data?.detail === 'string' ? data.detail : undefined
      const first = data ? Object.values(data).flat().find((v) => typeof v === 'string') : undefined
      setError(detail || (first as string | undefined) || 'Saqlashda xato')
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

  return (
    <div className="page" style={{ maxWidth: 520 }}>
      <h1 className="page-title">Tana oʻlchovlari</h1>

      {locked && (
        <div
          style={{
            background: 'var(--warning-bg)',
            border: '1px solid rgba(245,184,75,.3)',
            borderRadius: 'var(--radius-sm)',
            padding: '12px 16px',
            marginBottom: 20,
            color: 'var(--warning)',
            fontSize: 14,
          }}
        >
          Oʻlchovlarni yiliga bir marta oʻzgartirish mumkin.
          {body?.measurements_unlock_at &&
            ` Keyingi oʻzgartirish: ${new Date(body.measurements_unlock_at).toLocaleDateString('uz-UZ')}.`}
        </div>
      )}

      <div className="card">
        <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 20 }}>
          Barcha oʻlchovlar santimetrda, aylana boʻyicha (masalan, koʻkrak aylanasi). Hammasi ixtiyoriy.
        </p>

        <form onSubmit={handleSubmit}>
          <div className="field">
            <label className="label" htmlFor="height">Boʻy (sm)</label>
            <input id="height" className="input" type="number" min="50" max="260" value={height}
              onChange={(e) => setHeight(e.target.value)} placeholder="masalan: 175" disabled={locked} />
          </div>
          {FIELDS.map((f) => (
            <div className="field" key={f.key}>
              <label className="label" htmlFor={f.key}>{f.label}</label>
              <input id={f.key} className="input" type="number" min="1" max="250" value={values[f.key]}
                onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                placeholder={f.placeholder} disabled={locked} />
            </div>
          ))}

          {error && <p className="error-text" style={{ marginBottom: 12 }}>{error}</p>}
          {success && (
            <p style={{ color: 'var(--accent)', fontSize: 13, marginBottom: 12 }}>
              Saqlandi
            </p>
          )}

          <div style={{ display: 'flex', gap: 12 }}>
            <button type="submit" className="btn btn-primary" disabled={saving || locked} style={{ flex: 1 }}>
              {saving ? 'Saqlanmoqda…' : 'Saqlash'}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => navigate('/')}>
              Orqaga
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
