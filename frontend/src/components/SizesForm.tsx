import type { GarmentType } from '../api/types'
import { FIT_TEXT, GARMENT_SIZE_LABELS } from '../locale/uz'
import { GARMENT_SIZE_FIELDS, type GarmentSizeKey, type SizeValues } from '../fit/sizeFields'
import SizeDiagram from './SizeDiagram'

interface Props {
  type: GarmentType
  values: SizeValues
  onChange: (values: SizeValues) => void
  stretch: boolean
  onStretch: (stretch: boolean) => void
  /** Shown under each field (client-side checks, after the first submit). */
  errors?: Partial<Record<GarmentSizeKey, string>>
  disabled?: boolean
}

/** Garment real size (flat-lay cm) + stretch, with the "where to measure" diagram (docs/11). */
export default function SizesForm({ type, values, onChange, stretch, onStretch, errors = {}, disabled }: Props) {
  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 4 }}>{FIT_TEXT.sizesTitle}</h2>
      <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 12 }}>{FIT_TEXT.sizesHelp}</p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'flex-start' }}>
        <div style={{ flex: '1 1 220px' }}><SizeDiagram type={type} /></div>
        <div style={{ flex: '1 1 220px' }}>
          {GARMENT_SIZE_FIELDS[type].map((f) => {
            const id = `size-${f.key}`
            return (
              <div className="field" key={f.key}>
                <label className="label" htmlFor={id}>
                  {GARMENT_SIZE_LABELS[f.key]} ({FIT_TEXT.cm})
                  {f.required
                    ? <span style={{ color: 'var(--danger)' }} title={FIT_TEXT.requiredMark}> *</span>
                    : <span style={{ color: 'var(--muted)', fontWeight: 400 }}> ({FIT_TEXT.optional})</span>}
                </label>
                <input id={id} className="input" type="number" inputMode="decimal" step="0.1" min={f.min} max={f.max}
                  placeholder={`${f.min}–${f.max}`} value={values[f.key] ?? ''} disabled={disabled}
                  aria-invalid={errors[f.key] ? true : undefined}
                  onChange={(e) => onChange({ ...values, [f.key]: e.target.value })} />
                {errors[f.key] && <p className="error-text" style={{ marginTop: 4 }}>{errors[f.key]}</p>}
              </div>
            )
          })}
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer' }}>
            <input type="checkbox" checked={stretch} disabled={disabled} onChange={(e) => onStretch(e.target.checked)}
              style={{ accentColor: 'var(--accent)' }} />
            {FIT_TEXT.stretch}
          </label>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>{FIT_TEXT.stretchHelp}</p>
        </div>
      </div>
    </div>
  )
}
