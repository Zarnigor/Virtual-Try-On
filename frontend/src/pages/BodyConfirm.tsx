import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getBody, confirmBody, deleteBody, type Body } from '../api/bodies'
import type { BodyLandmarks } from '../api/types'
import Spinner from '../components/Spinner'
import LandmarkEditor from '../components/landmark-editor/LandmarkEditor'
import { BODY_GROUPS, BODY_RULES } from '../components/landmark-editor/bodyGroups'

export default function BodyConfirm() {
  const navigate = useNavigate()
  const [body, setBody] = useState<Body | null>(null)
  const [loading, setLoading] = useState(true)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getBody()
      .then(({ data }) => setBody(data))
      .catch(() => setBody(null))
      .finally(() => setLoading(false))
  }, [])

  const handleConfirm = async (landmarks: Record<string, unknown>) => {
    if (!body) return
    if (!confirm('Tasdiqlangandan soʻng rasm va nuqtalarni oʻzgartirib boʻlmaydi. Tasdiqlaysizmi?')) return
    setConfirming(true)
    setError('')
    try {
      await confirmBody({ landmarks: landmarks as unknown as BodyLandmarks })
      navigate('/body/measurements')
    } catch (err: unknown) {
      const data = (err as { response?: { data?: { code?: string; detail?: string } } })?.response?.data
      setError(data?.code === 'LANDMARKS_INVALID' && data.detail ? data.detail : 'Tasdiqlashda xato. Qayta urinib koʻring.')
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

  return (
    <div className="page">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <button className="btn btn-secondary btn-sm" onClick={handleReupload}>Boshqa rasm yuklash</button>
        <p style={{ color: 'var(--text-soft)', fontSize: 14, margin: 0 }}>
          Nuqtalar avtomatik qoʻyildi. Tekshiring, kerak boʻlsa suring. Tasdiqlangandan soʻng oʻzgartirib boʻlmaydi.
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
          landmarks={body.landmarks}
          heading="Tana nuqtalari"
          subheading="Har bir chiziqning chap va oʻng nuqtasini tana chetiga qoʻying."
          saving={confirming}
          saveLabel="Tasdiqlash"
          onSave={handleConfirm}
        />
      ) : (
        <p className="error-text">Tana rasmi yoʻq. Qayta yuklang.</p>
      )}
    </div>
  )
}
