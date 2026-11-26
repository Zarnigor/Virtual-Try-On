import { Link } from 'react-router-dom'
import type { FitZoneCheck } from '../api/types'
import { FIT_TEXT } from '../locale/uz'
import { fitNotice } from '../fit/fitNotice'

/** One garment's fit-check answer (GET tryon/fit-check/ result or a POST tryon/ fit error). */
export interface FitAnswer {
  garmentId: number
  fits: boolean
  checks: FitZoneCheck[]
  /** too_large zones (docs/09 #128): rendered, but big. */
  warnings: FitZoneCheck[]
  code?: 'GARMENT_SIZE_MISSING' | 'BODY_SIZE_MISSING'
}

interface Props {
  answer: FitAnswer
  base: 'avatar' | 'body'
  /** The user owns the garment (only the owner can enter its sizes). */
  ownGarment: boolean
}

const style = { marginTop: 6, fontSize: 12 }

export default function FitNotice({ answer, base, ownGarment }: Props) {
  if (answer.code === 'GARMENT_SIZE_MISSING') {
    return (
      <div className="banner banner-warning" role="status" style={style}>
        {FIT_TEXT.garmentSizeMissing}{' '}
        {ownGarment && <Link to={`/garments/${answer.garmentId}/sizes`}>{FIT_TEXT.enterGarmentSizes}</Link>}
      </div>
    )
  }
  if (answer.code === 'BODY_SIZE_MISSING') {
    // Avatar sizes are staff data: the user cannot enter them, so no link (owner, 2026-11-26).
    return (
      <div className="banner banner-warning" role="status" style={style}>
        {base === 'body'
          ? <>{FIT_TEXT.bodySizeMissing} <Link to="/body/measurements">{FIT_TEXT.enterYourSizes}</Link></>
          : FIT_TEXT.avatarSizeMissing}
      </div>
    )
  }
  const notice = fitNotice(answer)
  if (notice.kind === 'none') return null
  return <FitLines kind={notice.kind} lines={notice.lines} />
}

/** Red "Sizga mos emas" or yellow "Sizga katta" banner with one line per zone. */
export function FitLines({ kind, lines, title }: { kind: 'red' | 'yellow'; lines: string[]; title?: string | null }) {
  return (
    <div className={`banner ${kind === 'red' ? 'banner-danger' : 'banner-warning'}`} role="status"
      data-fit={kind} style={style}>
      {title && <div style={{ fontWeight: 600 }}>{title}</div>}
      <strong>{kind === 'red' ? FIT_TEXT.notFits : FIT_TEXT.tooLarge}</strong>
      <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
        {lines.map((l) => <li key={l}>{l}</li>)}
      </ul>
    </div>
  )
}
