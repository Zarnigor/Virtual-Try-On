import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadStaffAvatar } from '../../api/staff'
import type { Build, Sex } from '../../api/types'
import PhotoPicker from '../../components/PhotoPicker'

const FIELDS = [
  ['height_cm', 'Boʻy (sm)'], ['shoulder', 'Yelka aylanasi (sm)'], ['chest', 'Koʻkrak aylanasi (sm)'],
  ['waist', 'Bel aylanasi (sm)'], ['hip', 'Son aylanasi (sm)'],
] as const
type NumField = (typeof FIELDS)[number][0]

/** Staff: upload a new avatar photo (shared body pipeline on the backend), then open the landmark editor. */
export default function StaffAvatarNew() {
  const navigate = useNavigate()
  const [sex, setSex] = useState<Sex>('female')
  const [build, setBuild] = useState<Build>('average')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [nums, setNums] = useState<Record<NumField, string>>({ height_cm: '', shoulder: '', chest: '', waist: '', hip: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const ready = !!file && FIELDS.every(([k]) => Number(nums[k]) > 0)

  const submit = async () => {
    if (!file || !ready) return
    setLoading(true)
    setError('')
    try {
      const n = (k: NumField) => Number(nums[k])
      const { data } = await uploadStaffAvatar({
        sex, build, photo: file, height_cm: n('height_cm'), shoulder: n('shoulder'), chest: n('chest'), waist: n('waist'), hip: n('hip'),
      })
      navigate(`/staff/avatars/${data.id}`)
    } catch (err: unknown) {
      const data = (err as { response?: { data?: Record<string, unknown> } })?.response?.data
      setError(typeof data?.detail === 'string' ? data.detail : 'Yuklab boʻlmadi. Maydonlarni tekshiring.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page" style={{ maxWidth: 640 }}>
      <button className="btn btn-secondary btn-sm" style={{ marginBottom: 16 }} onClick={() => navigate('/staff/avatars')}>← Orqaga</button>
      <h1 className="page-title">Yangi avatar</h1>
      <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 16 }}>
        Shu jins va qomatdagi avatar boʻlsa, uning rasmi va nuqtalari almashtiriladi (nuqtalar qayta tasdiqlanadi).
      </p>

      <div className="card" style={{ marginBottom: 20, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
        <div className="field">
          <label className="label" htmlFor="sex">Jins</label>
          <select id="sex" className="input" value={sex} onChange={(e) => setSex(e.target.value as Sex)}>
            <option value="female">Ayol</option>
            <option value="male">Erkak</option>
          </select>
        </div>
        <div className="field">
          <label className="label" htmlFor="build">Qomat</label>
          <select id="build" className="input" value={build} onChange={(e) => setBuild(e.target.value as Build)}>
            <option value="slim">Ozgʻin</option>
            <option value="average">Oʻrtacha</option>
            <option value="plus">Toʻla</option>
          </select>
        </div>
        {FIELDS.map(([k, label]) => (
          <div className="field" key={k}>
            <label className="label" htmlFor={k}>{label}</label>
            <input
              id={k} className="input" type="number" inputMode="decimal" min={1} value={nums[k]}
              onChange={(e) => setNums((p) => ({ ...p, [k]: e.target.value }))}
            />
          </div>
        ))}
      </div>

      <PhotoPicker
        file={file}
        preview={preview}
        onFile={(f) => { setFile(f); setPreview(URL.createObjectURL(f)); setError('') }}
        onClear={() => { setFile(null); setPreview(null) }}
        label="Avatar rasmini tanlang (A-poza, butun gavda, old tomondan)"
      />

      {error && <p className="error-text" style={{ marginTop: 12 }}>{error}</p>}
      <button className="btn btn-primary" style={{ marginTop: 20, width: '100%' }} disabled={!ready || loading} onClick={submit}>
        {loading ? 'Qayta ishlanmoqda… (bir necha soniya)' : 'Yuklash va nuqtalarni belgilash'}
      </button>
    </div>
  )
}
