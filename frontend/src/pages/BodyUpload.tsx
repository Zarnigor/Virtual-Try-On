import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadBody } from '../api/bodies'
import type { Sex } from '../api/types'
import PhotoPicker from '../components/PhotoPicker'
import { Segmented } from '../components/GarmentSettingsPanel'
import { BODY_UPLOAD, SEX_LABELS } from '../locale/uz'

export default function BodyUpload() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [adult, setAdult] = useState(false)
  const [sex, setSex] = useState<Sex | null>(null)

  const handleFile = (f: File) => {
    setFile(f)
    setPreview(URL.createObjectURL(f))
    setError('')
  }

  const handleUpload = async () => {
    if (!file || !adult) return
    if (!sex) {
      setError(BODY_UPLOAD.sexRequired)
      return
    }
    setLoading(true)
    setError('')
    try {
      const { data } = await uploadBody(file, adult, sex)
      navigate('/body/waiting', { state: { jobId: data.job_id } })
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Yuklab boʻlmadi')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page" style={{ maxWidth: 640 }}>
      <h1 className="page-title">Tana rasmini yuklash</h1>

      <div className="card" style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 16, marginBottom: 12, color: 'var(--warning)' }}>
          Muhim talablar
        </h2>
        <ul style={{ paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[
            'A-poza: qoʻllar yon tomonga yoyilgan, oyoqlar biroz ajratilgan',
            'Old tomondan, butun gavda koʻrinishi',
            'Yengil, tenga yaqin kiyim: qisqa yengli yoki yengsiz koʻylak + shim/legging',
            'Yaxshi yoritilgan, tekis fon',
            '18 yoshdan katta foydalanuvchilar uchun',
          ].map((item, i) => (
            <li key={i} style={{ color: 'var(--text-soft)', fontSize: 14 }}>{item}</li>
          ))}
        </ul>
      </div>

      <PhotoPicker
        file={file}
        preview={preview}
        onFile={handleFile}
        onClear={() => { setFile(null); setPreview(null) }}
      />

      <div style={{ marginTop: 16 }}>
        <Segmented<Sex> title={BODY_UPLOAD.sexTitle} value={sex ?? ''} options={SEX_LABELS} onChange={setSex} />
        <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>{BODY_UPLOAD.sexHelp}</p>
      </div>

      <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginTop: 16, cursor: 'pointer' }}>
        <input
          type="checkbox"
          checked={adult}
          onChange={(e) => setAdult(e.target.checked)}
          style={{ width: 18, height: 18, marginTop: 2, accentColor: 'var(--accent)', flexShrink: 0 }}
        />
        <span style={{ fontSize: 14, color: 'var(--text-soft)', lineHeight: 1.4 }}>
          Men 18 yoshdan kattaman
        </span>
      </label>

      {error && <p className="error-text" style={{ marginTop: 12 }}>{error}</p>}

      <div style={{ marginTop: 20, display: 'flex', gap: 12 }}>
        <button
          className="btn btn-primary"
          onClick={handleUpload}
          disabled={!file || !adult || !sex || loading}
          style={{ flex: 1 }}
        >
          {loading ? 'Yuklanmoqda…' : 'Yuklash'}
        </button>
      </div>
    </div>
  )
}
