import { useState } from 'react'
import { updateGarmentSettings, type Garment } from '../api/garments'
import type { FitMode, GarmentGender, GarmentSettings } from '../api/types'
import { GARMENT_SETTINGS as T } from '../locale/uz'

/**
 * Screen 9: per-garment fit mode and gender (docs/09 #93). Each click saves at once with
 * PATCH garments/{id}/ (the same pattern as visibility). The image is never editable.
 */
export default function GarmentSettingsPanel({ garment, onSaved }: { garment: Garment; onSaved: (g: Garment) => void }) {
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<'' | 'saved' | 'error'>('')

  const save = async (patch: GarmentSettings) => {
    setSaving(true)
    setStatus('')
    try {
      const { data } = await updateGarmentSettings(garment.id, patch)
      onSaved(data)
      setStatus('saved')
    } catch {
      setStatus('error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card garment-settings">
      <Segmented<FitMode>
        title={T.fitTitle}
        value={garment.fit_mode}
        options={T.fit}
        disabled={saving}
        onChange={(fit_mode) => save({ fit_mode })}
      />
      <p className="seg-help">{T.fitHelp[garment.fit_mode]}</p>
      <Segmented<GarmentGender>
        title={T.genderTitle}
        value={garment.gender}
        options={T.gender}
        disabled={saving}
        onChange={(gender) => save({ gender })}
      />
      {status === 'saved' && <p className="seg-status" role="status">{T.saved}</p>}
      {status === 'error' && <p className="error-text" role="alert">{T.saveError}</p>}
    </div>
  )
}

export function Segmented<V extends string>({ title, value, options, disabled, onChange }: {
  title: string
  value: V | ''
  options: Record<V, string>
  disabled?: boolean
  onChange: (v: V) => void
}) {
  return (
    <div className="seg-row">
      <span className="seg-title">{title}</span>
      <div className="seg" role="group" aria-label={title}>
        {(Object.keys(options) as V[]).map((v) => (
          <button key={v} type="button" aria-pressed={value === v} disabled={disabled} onClick={() => value !== v && onChange(v)}>
            {options[v]}
          </button>
        ))}
      </div>
    </div>
  )
}

/** Small gender badge for garment lists. */
export function GenderBadge({ gender }: { gender: GarmentGender }) {
  return <span className="gender-badge" data-gender={gender}>{T.gender[gender]}</span>
}
