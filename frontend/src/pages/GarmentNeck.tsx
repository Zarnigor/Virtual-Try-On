import { useCallback, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { updateLandmarks } from '../api/garments'
import type { GarmentLandmarks } from '../api/types'
import Spinner from '../components/Spinner'
import LandmarkEditor from '../components/landmark-editor/LandmarkEditor'
import { TSHIRT_NECK_GROUPS, TSHIRT_NECK_RULES } from '../components/landmark-editor/garmentGroups'
import { checkGarment } from '../components/landmark-editor/garmentChecks'
import {
  guessNeckShape, neckView, storedPolygon, suggestNeckHole, type NeckShape,
} from '../components/landmark-editor/neckHole'
import { LANDMARK_EDITOR, NECK_EDITOR } from '../locale/uz'
import { saveErrorText, useGarmentImage } from './useGarmentImage'

/**
 * Screen 9, step 2 (T-shirts, docs/10, docs/09 #102): the three collar points + the neckline hole polygon, zoomed
 * to the top centre of the garment. Save sends the full landmarks (step-1 points kept) with `neck_hole.polygon`;
 * "Oʻtkazib yuborish" leaves without saving (the try-on keeps the r7 neckline).
 */
export default function GarmentNeckPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { garment, size, alpha, loading, error, setError } = useGarmentImage(id)
  const [saving, setSaving] = useState(false)
  const [success, setSuccess] = useState(false)
  const [serverWarnings, setServerWarnings] = useState<string[]>([])

  const check = useCallback(
    (lm: Record<string, unknown>) =>
      checkGarment('tshirt', lm, alpha.bbox, 'neck', size ? { w: size.w, h: size.h, alpha } : undefined),
    [alpha, size],
  )
  // the suggestion closes along the garment's top edge (alpha box top) so the inner back is inside the hole
  const polygon = useMemo(
    () => (garment ? {
      initial: storedPolygon(garment.landmarks),
      suggest: (lm: Record<string, unknown>, shape: NeckShape) => suggestNeckHole(lm, shape, alpha.bbox?.y0 ?? null),
      guess: guessNeckShape,
    } : undefined),
    [garment, alpha],
  )
  const view = useMemo(() => (size ? neckView(size.w, size.h, alpha.bbox) : undefined), [size, alpha])

  const handleSave = async (landmarks: Record<string, unknown>) => {
    if (!id) return
    setSaving(true)
    setError('')
    setSuccess(false)
    try {
      const { sleeve_end: _legacy, ...rest } = landmarks
      void _legacy
      const { data } = await updateLandmarks(Number(id), rest as unknown as GarmentLandmarks)
      const warnings = (data.landmark_warnings ?? []).map((w) => w.detail)
      setServerWarnings(warnings)
      setSuccess(true)
      setTimeout(() => navigate('/wardrobe'), warnings.length ? 3500 : 1200)
    } catch (err: unknown) {
      setError(saveErrorText(err))
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

  if (garment && garment.type !== 'tshirt') {
    return (
      <div className="page">
        <p className="error-text">Bu qadam faqat futbolka uchun.</p>
        <Link to="/wardrobe" className="btn btn-secondary btn-sm">{LANDMARK_EDITOR.back}</Link>
      </div>
    )
  }

  return (
    <div className="page">
      <div style={{ marginBottom: 16 }}>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate(`/garments/${id}/landmarks`)}>
          {LANDMARK_EDITOR.back}
        </button>
      </div>

      {garment && !garment.landmarks_complete && (
        <div className="banner banner-warning" role="status" style={{ marginBottom: 12 }}>
          {NECK_EDITOR.needStep1}{' '}
          <Link to={`/garments/${id}/landmarks`}>{NECK_EDITOR.goStep1}</Link>
        </div>
      )}
      {error && <p className="error-text" style={{ marginBottom: 12 }}>{error}</p>}
      {success && (
        <p role="status" style={{ color: 'var(--accent)', fontSize: 13, marginBottom: 12 }}>{NECK_EDITOR.saved}</p>
      )}
      {serverWarnings.length > 0 && (
        <ul className="banner banner-warning" role="status" style={{ marginBottom: 12 }}>
          {serverWarnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}

      {garment && size && garment.image_url && (
        <>
          <LandmarkEditor
            imageUrl={garment.image_url}
            imageAlt="Futbolka rasmi, yoqa qismi"
            bounds={size}
            groups={TSHIRT_NECK_GROUPS}
            rules={TSHIRT_NECK_RULES}
            landmarks={garment.landmarks}
            heading={NECK_EDITOR.heading}
            subheading={NECK_EDITOR.subheading}
            stepLabel={LANDMARK_EDITOR.step(2, 2)}
            view={view}
            polygon={polygon}
            saving={saving}
            onSave={handleSave}
            check={check}
            extraActions={
              <button
                type="button" className="btn btn-secondary" onClick={() => navigate('/wardrobe')} disabled={saving}
                title={NECK_EDITOR.skipHint}
              >
                {NECK_EDITOR.skip}
              </button>
            }
          />
          <p className="le-hint" style={{ marginTop: 8 }}>{NECK_EDITOR.skipHint}</p>
        </>
      )}
    </div>
  )
}
