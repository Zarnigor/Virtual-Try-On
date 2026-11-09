import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getGarment, updateLandmarks, type Garment } from '../api/garments'
import type { GarmentLandmarks } from '../api/types'
import Spinner from '../components/Spinner'
import LandmarkEditor from '../components/landmark-editor/LandmarkEditor'
import { groupsFor } from '../components/landmark-editor/garmentGroups'

/** Screen 9: mark the garment landmarks. The image and landmarks come from the backend. */
export default function GarmentLandmarksPage() {
  const { id } = useParams()
  const navigate = useNavigate()

  const [garment, setGarment] = useState<Garment | null>(null)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    if (!id) return
    let alive = true
    getGarment(Number(id))
      .then(({ data }) => {
        if (!alive) return
        setGarment(data)
        if (!data.image_url) {
          setError('Kiyim hali tayyorlanmoqda. Biroz kuting va sahifani yangilang.')
          setLoading(false)
          return
        }
        const img = new Image()
        img.onload = () => {
          if (!alive) return
          setSize({ w: img.naturalWidth, h: img.naturalHeight })
          setLoading(false)
        }
        img.onerror = () => {
          if (!alive) return
          setError('Kiyim rasmini yuklab boʻlmadi')
          setLoading(false)
        }
        img.src = data.image_url
      })
      .catch(() => {
        if (!alive) return
        setError('Kiyim topilmadi')
        setLoading(false)
      })
    return () => { alive = false }
  }, [id])

  const groups = useMemo(() => (garment ? groupsFor(garment.type) : []), [garment])

  const handleSave = async (landmarks: Record<string, unknown>) => {
    if (!id) return
    setSaving(true)
    setError('')
    setSuccess(false)
    try {
      await updateLandmarks(Number(id), landmarks as unknown as GarmentLandmarks)
      setSuccess(true)
      setTimeout(() => navigate('/wardrobe'), 1200)
    } catch {
      setError('Saqlashda xato. Qayta urinib koʻring.')
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

  return (
    <div className="page">
      <div style={{ marginBottom: 16 }}>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/wardrobe')}>
          ← Orqaga
        </button>
      </div>

      {error && <p className="error-text" style={{ marginBottom: 12 }}>{error}</p>}
      {success && (
        <p role="status" style={{ color: 'var(--accent)', fontSize: 13, marginBottom: 12 }}>
          Muvaffaqiyatli saqlandi
        </p>
      )}

      {garment && size && garment.image_url && (
        <LandmarkEditor
          imageUrl={garment.image_url}
          imageAlt={garment.type === 'pants' ? 'Shim rasmi' : 'Futbolka rasmi'}
          bounds={size}
          groups={groups}
          landmarks={garment.landmarks}
          heading={`Belgi nuqtalari · ${garment.type === 'pants' ? 'Shim' : 'Futbolka'}`}
          subheading="Bitta chiziq tanlanadi, lupa bilan aniq joylanadi. Qolganlari xiralashadi."
          saving={saving}
          onSave={handleSave}
        />
      )}
    </div>
  )
}
