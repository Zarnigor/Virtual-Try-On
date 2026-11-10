import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getStaffAvatar, saveStaffAvatarLandmarks, type StaffAvatar } from '../../api/staff'
import type { BodyLandmarks } from '../../api/types'
import Spinner from '../../components/Spinner'
import StatusChip from '../../components/StatusChip'
import LandmarkEditor from '../../components/landmark-editor/LandmarkEditor'
import { BODY_GROUPS, BODY_RULES } from '../../components/landmark-editor/bodyGroups'
import { CIRCUMFERENCE_LINES, estimateCircumferences, type CircumferenceLine } from '../../components/landmark-editor/bodyMeasure'
import MeasurePanel from './MeasurePanel'

type Circ = Record<CircumferenceLine, string>
const EMPTY: Circ = { shoulder: '', chest: '', waist: '', hip: '' }

/** Confirmed avatars show their saved circumferences; auto-detected ones start from the ellipse estimate. */
function initialCirc(a: StaffAvatar): Circ {
  const est = a.height_cm ? estimateCircumferences(a.landmarks, a.height_cm) : {}
  const out = { ...EMPTY }
  for (const k of CIRCUMFERENCE_LINES) {
    const v = a.status === 'confirmed' ? a.measurements?.[k] ?? est[k] : est[k] ?? a.measurements?.[k]
    out[k] = v === undefined ? '' : String(v)
  }
  return out
}

/** Staff: mark an avatar's body landmarks. Saving sets landmarks_confirmed_at; the try-on engine uses them. */
export default function StaffAvatarEditor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [avatar, setAvatar] = useState<StaffAvatar | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [live, setLive] = useState<Record<string, unknown> | null>(null)
  const [height, setHeight] = useState('')
  const [circ, setCirc] = useState<Circ>(EMPTY)
  const onChange = useCallback((lm: Record<string, unknown>) => setLive(lm), [])

  useEffect(() => {
    getStaffAvatar(Number(id))
      .then(({ data }) => {
        setAvatar(data)
        setHeight(data.height_cm ? String(data.height_cm) : '')
        setCirc(initialCirc(data))
      })
      .catch(() => setError('Avatar topilmadi'))
  }, [id])

  const handleSave = async (landmarks: Record<string, unknown>) => {
    if (!avatar) return
    setSaving(true)
    setError('')
    setSaved(false)
    const h = Number(height)
    if (!(h >= 100 && h <= 250)) {
      setSaving(false)
      setError('Boʻyni 100 dan 250 sm gacha kiriting.')
      return
    }
    const measurements: Partial<Record<CircumferenceLine, number>> = {}
    for (const k of CIRCUMFERENCE_LINES) {
      const v = Number(circ[k])
      if (circ[k] !== '' && !(v >= 20 && v <= 300)) {
        setSaving(false)
        setError('Aylana 20 dan 300 sm gacha boʻlsin.')
        return
      }
      if (circ[k] !== '') measurements[k] = v
    }
    try {
      const { data } = await saveStaffAvatarLandmarks(avatar.id, {
        landmarks: landmarks as unknown as BodyLandmarks, height_cm: h, measurements,
      })
      setAvatar(data)
      setSaved(true)
    } catch (err: unknown) {
      const data = (err as { response?: { data?: { code?: string; detail?: string } } })?.response?.data
      setError(data?.code === 'LANDMARKS_INVALID' && data.detail ? data.detail : 'Saqlashda xato. Qayta urinib koʻring.')
    } finally {
      setSaving(false)
    }
  }

  if (!avatar) {
    return (
      <div className="page" style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
        {error ? <p className="error-text">{error}</p> : <Spinner size={40} />}
      </div>
    )
  }

  return (
    <div className="page">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/staff/avatars')}>← Orqaga</button>
        <StatusChip status={avatar.status} />
      </div>
      {error && <p className="error-text" style={{ marginBottom: 12 }}>{error}</p>}
      {saved && <p role="status" style={{ color: 'var(--accent)', fontSize: 13, marginBottom: 12 }}>Saqlandi. Sinab koʻrish shu nuqtalardan foydalanadi.</p>}
      {avatar.image_url ? (
        <LandmarkEditor
          imageUrl={avatar.image_url}
          imageAlt="Avatar rasmi"
          bounds={{ w: 600, h: 1200 }}
          groups={BODY_GROUPS}
          rules={BODY_RULES}
          landmarks={avatar.landmarks}
          heading={`Avatar nuqtalari · ${avatar.sex === 'male' ? 'Erkak' : 'Ayol'} ${avatar.build}`}
          subheading="Har bir chiziqning chap va oʻng nuqtasini tana chetiga qoʻying."
          saving={saving}
          onSave={handleSave}
          onChange={onChange}
        />
      ) : (
        <p className="error-text">Avatar rasmi yoʻq.</p>
      )}
      <MeasurePanel
        landmarks={live}
        height={height}
        onHeight={setHeight}
        circ={circ}
        onCirc={(line, v) => setCirc((p) => ({ ...p, [line]: v }))}
      />
    </div>
  )
}
