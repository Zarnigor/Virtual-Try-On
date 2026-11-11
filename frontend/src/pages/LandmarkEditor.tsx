import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getGarment, updateLandmarks, type Garment } from '../api/garments'
import type { GarmentLandmarks } from '../api/types'
import DevAiWarning from '../components/DevAiWarning'
import Spinner from '../components/Spinner'
import LandmarkEditor from '../components/landmark-editor/LandmarkEditor'
import { groupsFor, rulesFor } from '../components/landmark-editor/garmentGroups'
import { checkGarment, missingTshirtGroups, type BBox } from '../components/landmark-editor/garmentChecks'
import { LANDMARK_EDITOR } from '../locale/uz'

/** Visible pixels (alpha > 0) of the loaded image, or null when the canvas cannot read it (cross-origin). */
function alphaBBox(img: HTMLImageElement): BBox | null {
  try {
    const c = document.createElement('canvas')
    c.width = img.naturalWidth
    c.height = img.naturalHeight
    const ctx = c.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(img, 0, 0)
    const { data } = ctx.getImageData(0, 0, c.width, c.height)
    let x0 = c.width, y0 = c.height, x1 = -1, y1 = -1
    for (let y = 0; y < c.height; y++) {
      for (let x = 0; x < c.width; x++) {
        if (data[(y * c.width + x) * 4 + 3] > 0) {
          if (x < x0) x0 = x
          if (x > x1) x1 = x
          if (y < y0) y0 = y
          if (y > y1) y1 = y
        }
      }
    }
    return x1 < 0 ? null : { x0, y0, x1, y1 }
  } catch {
    return null // tainted canvas: the server still checks the bounding box
  }
}

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
  const [bbox, setBbox] = useState<BBox | null>(null)
  const [serverWarnings, setServerWarnings] = useState<string[]>([])

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
        img.crossOrigin = 'anonymous'
        img.onload = () => {
          if (!alive) return
          setSize({ w: img.naturalWidth, h: img.naturalHeight })
          setBbox(alphaBBox(img))
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
  const rules = useMemo(() => (garment ? rulesFor(garment.type) : undefined), [garment])
  const check = useCallback(
    (lm: Record<string, unknown>) => checkGarment(garment?.type ?? 'tshirt', lm, bbox),
    [garment, bbox],
  )
  const missing = garment?.type === 'tshirt' && !garment.landmarks_complete
    ? missingTshirtGroups(garment.landmarks) : []

  const handleSave = async (landmarks: Record<string, unknown>) => {
    if (!id) return
    setSaving(true)
    setError('')
    setSuccess(false)
    try {
      const { sleeve_end: _legacy, ...rest } = landmarks // legacy, never written (the server drops it too)
      void _legacy
      const { data } = await updateLandmarks(Number(id), rest as unknown as GarmentLandmarks)
      const warnings = (data.landmark_warnings ?? []).map((w) => w.detail)
      setServerWarnings(warnings)
      setSuccess(true)
      setTimeout(() => navigate('/wardrobe'), warnings.length ? 3500 : 1200)
    } catch (err: unknown) {
      // LANDMARKS_INVALID carries a short Uzbek message naming the group; show it as is.
      const data = (err as { response?: { data?: { code?: string; detail?: string } } })?.response?.data
      setError(data?.code === 'LANDMARKS_INVALID' && data.detail ? data.detail : 'Saqlashda xato. Qayta urinib koʻring.')
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

      {garment?.ai_skipped && <DevAiWarning />}
      {missing.length > 0 && (
        <div className="banner banner-warning" role="status" style={{ marginBottom: 12 }}>
          {LANDMARK_EDITOR.incompleteBanner(missing)}
        </div>
      )}
      {error && <p className="error-text" style={{ marginBottom: 12 }}>{error}</p>}
      {success && (
        <p role="status" style={{ color: 'var(--accent)', fontSize: 13, marginBottom: 12 }}>
          Muvaffaqiyatli saqlandi
        </p>
      )}
      {serverWarnings.length > 0 && (
        <ul className="banner banner-warning" role="status" style={{ marginBottom: 12 }}>
          {serverWarnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}

      {garment && size && garment.image_url && (
        <LandmarkEditor
          imageUrl={garment.image_url}
          imageAlt={garment.type === 'pants' ? 'Shim rasmi' : 'Futbolka rasmi'}
          bounds={size}
          groups={groups}
          rules={rules}
          landmarks={garment.landmarks}
          heading={`Belgi nuqtalari · ${garment.type === 'pants' ? 'Shim' : 'Futbolka'}`}
          subheading="Bitta chiziq tanlanadi, lupa bilan aniq joylanadi. Qolganlari xiralashadi."
          saving={saving}
          onSave={handleSave}
          check={check}
        />
      )}
    </div>
  )
}
