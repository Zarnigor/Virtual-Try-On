import type { GarmentType } from '../api/types'
import { FIT_TEXT, GARMENT_SIZE_LABELS } from '../locale/uz'
import type { GarmentSizeKey } from '../fit/sizeFields'

/** "Where to measure": a flat-lay outline with labelled arrows (inline SVG, no external images, docs/11). */
interface Arrow { key: GarmentSizeKey; letter: string; x1: number; y1: number; x2: number; y2: number; lx: number; ly: number; hint: string }

const SHAPES: Record<GarmentType, { path: string; arrows: Arrow[] }> = {
  tshirt: {
    path: 'M105 24 Q130 42 155 24 L190 36 L235 84 L212 106 L180 86 L180 204 L80 204 L80 86 L48 106 L25 84 L70 36 Z',
    arrows: [
      { key: 'chest_width', letter: 'A', x1: 82, y1: 94, x2: 178, y2: 94, lx: 130, ly: 88, hint: FIT_TEXT.diagramChest },
      { key: 'length', letter: 'B', x1: 166, y1: 32, x2: 166, y2: 202, lx: 156, ly: 130, hint: FIT_TEXT.diagramLength },
      { key: 'shoulder_width', letter: 'C', x1: 70, y1: 14, x2: 190, y2: 14, lx: 130, ly: 10, hint: FIT_TEXT.diagramShoulder },
      { key: 'waist_width', letter: 'D', x1: 82, y1: 156, x2: 152, y2: 156, lx: 117, ly: 150, hint: FIT_TEXT.diagramWaist },
      { key: 'sleeve_length', letter: 'E', x1: 196, y1: 30, x2: 240, y2: 76, lx: 226, ly: 46, hint: FIT_TEXT.diagramSleeve },
    ],
  },
  pants: {
    path: 'M70 16 L190 16 L196 62 L200 212 L140 212 L130 102 L120 212 L60 212 L64 62 Z',
    arrows: [
      { key: 'waist_width', letter: 'A', x1: 72, y1: 26, x2: 188, y2: 26, lx: 130, ly: 40, hint: FIT_TEXT.diagramPantsWaist },
      { key: 'hip_width', letter: 'B', x1: 66, y1: 62, x2: 194, y2: 62, lx: 130, ly: 76, hint: FIT_TEXT.diagramHip },
      { key: 'inseam', letter: 'C', x1: 140, y1: 108, x2: 147, y2: 208, lx: 156, ly: 160, hint: FIT_TEXT.diagramInseam },
      { key: 'thigh_width', letter: 'D', x1: 63, y1: 116, x2: 125, y2: 116, lx: 94, ly: 110, hint: FIT_TEXT.diagramThigh },
      { key: 'leg_opening', letter: 'E', x1: 62, y1: 200, x2: 118, y2: 200, lx: 90, ly: 194, hint: FIT_TEXT.diagramLeg },
    ],
  },
}

export default function SizeDiagram({ type }: { type: GarmentType }) {
  const shape = SHAPES[type]
  const markerId = `size-arrow-${type}`
  return (
    <figure style={{ margin: 0 }}>
      <figcaption style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>{FIT_TEXT.whereToMeasure}</figcaption>
      <svg viewBox="0 0 260 222" width="100%" style={{ maxWidth: 280, color: 'var(--accent)' }} role="img"
        aria-label={FIT_TEXT.diagramAlt}>
        <defs>
          <marker id={markerId} viewBox="0 0 10 10" refX="5" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 Z" fill="currentColor" />
          </marker>
        </defs>
        <path d={shape.path} fill="var(--inset)" stroke="var(--border-strong)" strokeWidth="2" strokeLinejoin="round" />
        {shape.arrows.map((a) => (
          <g key={a.key}>
            <line x1={a.x1} y1={a.y1} x2={a.x2} y2={a.y2} stroke="currentColor" strokeWidth="1.8"
              markerStart={`url(#${markerId})`} markerEnd={`url(#${markerId})`} />
            <text x={a.lx} y={a.ly} fontSize="11" fontWeight="700" textAnchor="middle" fill="currentColor">{a.letter}</text>
          </g>
        ))}
      </svg>
      <ul style={{ listStyle: 'none', padding: 0, margin: '6px 0 0', fontSize: 12, color: 'var(--muted)' }}>
        {shape.arrows.map((a) => (
          <li key={a.key}>
            <strong style={{ color: 'var(--accent)' }}>{a.letter}</strong> {GARMENT_SIZE_LABELS[a.key]}: {a.hint}
          </li>
        ))}
      </ul>
    </figure>
  )
}
