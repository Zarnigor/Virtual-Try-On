import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadGarment } from '../api/garments'
import { usePoll } from '../components/usePoll'
import Dropzone from '../components/Dropzone'
import Spinner from '../components/Spinner'

// Same limits as the backend settings (MAX_UPLOAD_MB, GARMENT_MIN_SIDE_PX).
const MAX_UPLOAD_MB = 20
const MIN_SIDE_PX = 300

export default function GarmentUpload() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [type, setType] = useState<'tshirt' | 'pants'>('tshirt')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [jobId, setJobId] = useState<number | null>(null)
  const [garmentId, setGarmentId] = useState<number | null>(null)

  const { job } = usePoll(jobId)

  useEffect(() => {
    if (job?.status === 'done' && garmentId) {
      navigate(`/garments/${garmentId}/landmarks`)
    }
  }, [job, garmentId, navigate])

  // UX only: the server checks the real bytes again (backend/apps/images.py) and its message wins.
  const handleFile = (f: File) => {
    setError('')
    if (!['image/jpeg', 'image/png'].includes(f.type)) {
      setError('Faqat JPG yoki PNG formatidagi rasmlar qabul qilinadi.')
      return
    }
    if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setError(`Fayl hajmi juda katta. ${MAX_UPLOAD_MB} MB dan kichik rasm yuklang.`)
      return
    }
    const url = URL.createObjectURL(f)
    const img = new Image()
    img.onload = () => {
      if (Math.min(img.naturalWidth, img.naturalHeight) < MIN_SIDE_PX) {
        URL.revokeObjectURL(url)
        setError(`Rasm juda kichik. Rasmning har bir tomoni kamida ${MIN_SIDE_PX} px boʻlsin.`)
        return
      }
      setFile(f)
      setPreview(url)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      setError('Rasm fayli buzilgan yoki toʻliq yuklanmagan. Boshqa rasm tanlang.')
    }
    img.src = url
  }

  const handleUpload = async () => {
    if (!file) return
    setLoading(true)
    setError('')
    try {
      const { data } = await uploadGarment(file, type)
      setJobId(data.job_id)
      setGarmentId(data.garment.id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Yuklab boʻlmadi')
      setLoading(false)
    }
  }

  if (jobId && job) {
    return (
      <div
        className="page"
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: 400,
          gap: 20,
          textAlign: 'center',
        }}
      >
        {job.status === 'failed' ? (
          <>
            <h2>Kiyim tozalanmadi</h2>
            <p style={{ color: 'var(--danger)' }}>
              {job.error_message || 'Qayta urinib koʻring.'}
            </p>
            <button className="btn btn-primary" onClick={() => { setJobId(null); setLoading(false) }}>
              Qayta yuklash
            </button>
          </>
        ) : (
          <>
            <Spinner size={48} />
            <h2>Kiyim tayyorlanmoqda</h2>
            <p style={{ color: 'var(--muted)' }}>
              Orqa fon olib tashlanmoqda…
            </p>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="page" style={{ maxWidth: 560 }}>
      <h1 className="page-title">Kiyim yuklash</h1>

      <div className="card">
        <div className="field">
          <label className="label">Kiyim turi</label>
          <div style={{ display: 'flex', gap: 10 }}>
            {(['tshirt', 'pants'] as const).map((t) => (
              <label
                key={t}
                style={{
                  flex: 1,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 8,
                  minHeight: 48,
                  border: `1px solid ${type === t ? 'var(--accent)' : 'var(--border-strong)'}`,
                  borderRadius: 'var(--radius-sm)',
                  background: type === t ? 'var(--accent-soft)' : 'var(--inset)',
                  cursor: 'pointer',
                  color: type === t ? 'var(--accent)' : 'var(--text-soft)',
                  fontSize: 15,
                  fontWeight: 500,
                  transition: 'all 0.15s',
                }}
              >
                <input
                  type="radio"
                  name="garment_type"
                  value={t}
                  checked={type === t}
                  onChange={() => setType(t)}
                  style={{ display: 'none' }}
                />
                {t === 'tshirt' ? 'Futbolka' : 'Shim'}
              </label>
            ))}
          </div>
        </div>

        {preview ? (
          <div style={{ marginBottom: 16 }}>
            <img
              src={preview}
              alt="Tanlangan kiyim"
              style={{
                width: '100%',
                maxHeight: 300,
                objectFit: 'contain',
                borderRadius: 'var(--radius-md)',
                background: 'var(--inset)',
                marginBottom: 10,
              }}
            />
            <button className="btn btn-secondary btn-sm" onClick={() => { setFile(null); setPreview(null) }}>
              Boshqa rasm
            </button>
          </div>
        ) : (
          <Dropzone
            onFile={handleFile}
            accept="image/jpeg,image/png"
            label="Kiyim rasmini tanlang"
            hint="Oq yoki toza fonli rasm tavsiya etiladi"
          />
        )}

        {error && <p className="error-text" style={{ marginTop: 10 }}>{error}</p>}

        <button
          className="btn btn-primary"
          style={{ width: '100%', marginTop: 16 }}
          onClick={handleUpload}
          disabled={!file || loading}
        >
          {loading ? 'Yuklanmoqda…' : 'Yuklash'}
        </button>
      </div>
    </div>
  )
}
