import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { updateLandmarks } from '../api/garments'
import type { GarmentLandmarks } from '../api/types'
import DevAiWarning from '../components/DevAiWarning'
import GarmentSettingsPanel from '../components/GarmentSettingsPanel'
import Spinner from '../components/Spinner'
import LandmarkEditor from '../components/landmark-editor/LandmarkEditor'
import { mainGroupsFor, mainRulesFor } from '../components/landmark-editor/garmentGroups'
import { checkGarment, missingTshirtGroups } from '../components/landmark-editor/garmentChecks'
import { LANDMARK_EDITOR } from '../locale/uz'
import { saveErrorText, useGarmentImage } from './useGarmentImage'

/**
 * Screen 9, step 1 (docs/10, docs/09 #102): the main garment landmarks. T-shirts: everything except the collar
 * points, "Keyingi" saves and opens step 2 (/garments/{id}/neck). Pants: one step, Save -> wardrobe.
 * The saved payload is the FULL landmarks object: the stored collar / collar_bottom / neck_hole are kept untouched.
 */
export default function GarmentLandmarksPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { garment, setGarment, size, alpha, loading, error, setError } = useGarmentImage(id)

  const [saving, setSaving] = useState(false)
  const [success, setSuccess] = useState(false)
  const [serverWarnings, setServerWarnings] = useState<string[]>([])

  const isTshirt = garment?.type === 'tshirt'
  const groups = useMemo(() => (garment ? mainGroupsFor(garment.type) : []), [garment])
  const rules = useMemo(() => (garment ? mainRulesFor(garment.type) : undefined), [garment])
  const check = useCallback(
    (lm: Record<string, unknown>) => checkGarment(garment?.type ?? 'tshirt', lm, alpha.bbox, 'main'),
    [garment, alpha],
  )
  const missing = isTshirt && !garment?.landmarks_complete ? missingTshirtGroups(garment?.landmarks) : []

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
      const next = isTshirt ? `/garments/${id}/neck` : '/wardrobe'
      setTimeout(() => navigate(next), warnings.length ? 3500 : isTshirt ? 400 : 1200)
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

  return (
    <div className="page">
      <div style={{ marginBottom: 16 }}>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/wardrobe')}>
          {LANDMARK_EDITOR.back}
        </button>
      </div>

      {garment?.ai_skipped && <DevAiWarning />}
      {garment?.owned_by_me && <GarmentSettingsPanel garment={garment} onSaved={setGarment} />}
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
          stepLabel={isTshirt ? LANDMARK_EDITOR.step(1, 2) : undefined}
          saveLabel={isTshirt ? LANDMARK_EDITOR.next : undefined}
          saving={saving}
          onSave={handleSave}
          check={check}
        />
      )}
    </div>
  )
}
