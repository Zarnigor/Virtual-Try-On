import { Link } from 'react-router-dom'
import type { FitZoneCheck } from '../api/types'
import { FIT_TEXT } from '../locale/uz'
import { fitLines } from '../fit/fitMessages'

/** One garment's fit-check answer (GET tryon/fit-check/ result or a POST tryon/ fit error). Nothing when it fits. */
export interface FitAnswer {
  garmentId: number
  fits: boolean
  checks: FitZoneCheck[]
  code?: 'GARMENT_SIZE_MISSING' | 'BODY_SIZE_MISSING'
}

interface Props {
  answer: FitAnswer
  base: 'avatar' | 'body'
  /** The user owns the garment (only the owner can enter its sizes). */
  ownGarment: boolean
}

export default function FitNotice({ answer, base, ownGarment }: Props) {
  if (answer.fits) return null
  const style = { marginTop: 6, fontSize: 12 }
  if (answer.code === 'GARMENT_SIZE_MISSING') {
    return (
      <div className="banner banner-warning" role="status" style={style}>
        {FIT_TEXT.garmentSizeMissing}{' '}
        {ownGarment && <Link to={`/garments/${answer.garmentId}/sizes`}>{FIT_TEXT.enterGarmentSizes}</Link>}
      </div>
    )
  }
  if (answer.code === 'BODY_SIZE_MISSING') {
    return (
      <div className="banner banner-warning" role="status" style={style}>
        {FIT_TEXT.bodySizeMissing}{' '}
        {base === 'body'
          ? <Link to="/body/measurements">{FIT_TEXT.enterYourSizes}</Link>
          : <a href="#fit-sizes">{FIT_TEXT.enterYourSizes}</a>}
      </div>
    )
  }
  return (
    <div className="banner banner-warning" role="status" style={style}>
      <strong>{FIT_TEXT.notFits}</strong>
      <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
        {fitLines(answer.checks).map((l) => <li key={l}>{l}</li>)}
      </ul>
    </div>
  )
}
