import { CIRCUMFERENCE_LINES, WIDTH_ROWS, estimateCircumferences, widthCm, type CircumferenceLine } from '../../components/landmark-editor/bodyMeasure'

const LABEL: Record<CircumferenceLine, string> = { shoulder: 'Yelka', chest: 'Koʻkrak', waist: 'Bel', hip: 'Son' }

interface Props {
  landmarks: Record<string, unknown> | null
  height: string
  onHeight: (v: string) => void
  circ: Record<CircumferenceLine, string>
  onCirc: (line: CircumferenceLine, v: string) => void
}

/** Beside the staff editor: height, live width per line in cm, editable circumferences with the ellipse estimate. */
export default function MeasurePanel({ landmarks, height, onHeight, circ, onCirc }: Props) {
  const h = Number(height)
  const est = landmarks && h > 0 ? estimateCircumferences(landmarks, h) : {}
  return (
    <div className="card" style={{ marginTop: 20, display: 'grid', gap: 20, gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
      <div>
        <div className="field">
          <label className="label" htmlFor="height_cm">Boʻy (sm)</label>
          <input id="height_cm" className="input" type="number" inputMode="decimal" min={100} max={250}
            value={height} onChange={(e) => onHeight(e.target.value)} />
        </div>
        <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
          <caption style={{ textAlign: 'left', color: 'var(--muted)', marginBottom: 6 }}>Chiziq kengligi (old koʻrinish)</caption>
          <tbody>
            {WIDTH_ROWS.map((r) => {
              const w = landmarks && h > 0 ? widthCm(landmarks, h, ...r.path) : undefined
              return (
                <tr key={r.label} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '4px 0', color: 'var(--text-soft)' }}>{r.label}</td>
                  <td style={{ padding: '4px 0', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {w === undefined ? '—' : `${w.toFixed(1)} sm`}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 10 }}>
          Aylana (sm). Taxmin: ellips, chuqurlik = 0.6 × kenglik. Oʻzgartirish mumkin; Saqlash bilan saqlanadi.
        </p>
        {CIRCUMFERENCE_LINES.map((line) => (
          <div className="field" key={line}>
            <label className="label" htmlFor={`c-${line}`}>
              {LABEL[line]} aylanasi
              {est[line] !== undefined && (
                <span style={{ color: 'var(--muted)', fontWeight: 400 }}> · taxmin {est[line]} sm{' '}
                  <button type="button" className="btn btn-secondary btn-sm" style={{ marginLeft: 6, padding: '0 8px' }}
                    onClick={() => onCirc(line, String(est[line]))}>
                    olish
                  </button>
                </span>
              )}
            </label>
            <input id={`c-${line}`} className="input" type="number" inputMode="decimal" min={20} max={300}
              value={circ[line]} onChange={(e) => onCirc(line, e.target.value)} />
          </div>
        ))}
      </div>
    </div>
  )
}
