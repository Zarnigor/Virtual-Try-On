import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getGarment, updateGarmentSizes, type Garment } from '../api/garments'
import Spinner from '../components/Spinner'
import SizesForm from '../components/SizesForm'
import StatusChip from '../components/StatusChip'
import { GARMENT_SIZE_FIELDS, sizesToValues, validateSizes, type GarmentSizeKey, type SizeValues } from '../fit/sizeFields'
import { FIT_TEXT, GARMENT_SIZE_LABELS } from '../locale/uz'

/** /garments/:id/sizes: the garment's real size, view + edit (owner only; docs/11). PATCH replaces all sizes. */
export default function GarmentSizes() {
  const { id } = useParams()
  const [garment, setGarment] = useState<Garment | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [values, setValues] = useState<SizeValues>({})
  const [stretch, setStretch] = useState(false)
  const [errors, setErrors] = useState<Partial<Record<GarmentSizeKey, string>>>({})
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getGarment(Number(id))
      .then(({ data }) => {
        setGarment(data)
        setEditing(!data.sizes_complete)
        setValues(sizesToValues(data.type, data.sizes))
        setStretch(data.stretch)
      })
      .catch(() => setGarment(null))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return <div className="page" style={{ display: 'flex', justifyContent: 'center', padding: 80 }}><Spinner size={40} /></div>
  }
  if (!garment || !garment.owned_by_me) {
    return (
      <div className="page" style={{ maxWidth: 560 }}>
        <p className="error-text">{FIT_TEXT.notFound}</p>
        <Link to="/wardrobe" className="btn btn-secondary btn-sm">{FIT_TEXT.back}</Link>
      </div>
    )
  }

  const save = async () => {
    const checked = validateSizes(garment.type, values)
    setErrors(checked.errors)
    if (!checked.ok) return
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      const { data } = await updateGarmentSizes(garment.id, checked.sizes, stretch)
      setGarment(data)
      setValues(sizesToValues(data.type, data.sizes))
      setEditing(false)
      setSaved(true)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || FIT_TEXT.saveError)
    } finally {
      setSaving(false)
    }
  }

  const cancel = () => {
    setValues(sizesToValues(garment.type, garment.sizes))
    setStretch(garment.stretch)
    setErrors({})
    setError('')
    setEditing(false)
  }

  return (
    <div className="page" style={{ maxWidth: 760 }}>
      <h1 className="page-title">{FIT_TEXT.sizesPageTitle}</h1>
      <div className="card">
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16 }}>
          {garment.image_url && (
            <img src={garment.image_url} alt="Kiyim" style={{ width: 56, height: 72, objectFit: 'contain', borderRadius: 4 }} />
          )}
          <StatusChip status={garment.type} />
          {!garment.sizes_complete && <StatusChip status="sizes_missing" />}
        </div>

        {editing ? (
          <>
            <SizesForm type={garment.type} values={values} onChange={setValues} stretch={stretch}
              onStretch={setStretch} errors={errors} disabled={saving} />
            {error && <p className="error-text" role="alert" style={{ marginTop: 10 }}>{error}</p>}
            <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
              <button className="btn btn-primary" onClick={save} disabled={saving} style={{ flex: 1 }}>
                {saving ? FIT_TEXT.saving : FIT_TEXT.save}
              </button>
              {garment.sizes_complete && (
                <button className="btn btn-secondary" onClick={cancel} disabled={saving}>{FIT_TEXT.cancel}</button>
              )}
            </div>
          </>
        ) : (
          <>
            <dl style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 16px', fontSize: 14, margin: 0 }}>
              {GARMENT_SIZE_FIELDS[garment.type].map((f) => (
                <div key={f.key} style={{ display: 'contents' }}>
                  <dt style={{ color: 'var(--muted)' }}>{GARMENT_SIZE_LABELS[f.key]}</dt>
                  <dd style={{ margin: 0 }}>{garment.sizes?.[f.key] != null ? `${garment.sizes[f.key]} ${FIT_TEXT.cm}` : '—'}</dd>
                </div>
              ))}
              <dt style={{ color: 'var(--muted)' }}>{FIT_TEXT.stretch}</dt>
              <dd style={{ margin: 0 }}>{garment.stretch ? FIT_TEXT.stretchYes : FIT_TEXT.stretchNo}</dd>
            </dl>
            {saved && <p style={{ color: 'var(--accent)', fontSize: 13, marginTop: 12 }}>{FIT_TEXT.saved}</p>}
            <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
              <button className="btn btn-primary" onClick={() => { setSaved(false); setEditing(true) }}>{FIT_TEXT.edit}</button>
              <Link to="/wardrobe" className="btn btn-secondary">{FIT_TEXT.back}</Link>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
