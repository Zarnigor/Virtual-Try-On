import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent as ReactPointerEvent } from 'react'
import {
  NO_RULES, axisX, findPoint, fromLandmarks, movePoint, nudgePoint, saveState, snapCenters, toLandmarks,
  type Bounds, type EditorState, type GroupDef, type Rules,
} from './geometry'
import { hintFor } from './lineHints'
import './landmarkEditor.css'

/**
 * Landmark editor (design artboard "VariantC"). The image comes from the backend; the overlay is SVG
 * in image-pixel coordinates (viewBox = image size), so screen size never changes the saved values.
 */

interface Props {
  imageUrl: string
  imageAlt: string
  bounds: Bounds
  groups: GroupDef[]
  /** Order rules: a move stops at the neighbour instead of crossing it. Loading never clamps. */
  rules?: Rules
  /** Landmarks as loaded from the API (any shape the groups describe; empty object for new records). */
  landmarks: unknown
  heading: string
  subheading?: string
  saving?: boolean
  onSave: (landmarks: Record<string, unknown>) => void
  /** Called with the current landmarks after every change (e.g. live cm widths beside the editor). */
  onChange?: (landmarks: Record<string, unknown>) => void
}

const LOUPE_ZOOM = 3
const LOUPE_H = 220
const ARROWS: Record<string, [number, number]> = {
  ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0],
}

interface Drag { id: string; pointerId: number; offX: number; offY: number }

function hexA(hex: string, a: number) {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`
}

export default function LandmarkEditor({
  imageUrl, imageAlt, bounds, groups, rules = NO_RULES, landmarks, heading, subheading, saving, onSave, onChange,
}: Props) {
  const { w, h } = bounds
  const initial = useMemo(() => fromLandmarks(landmarks, groups, { w, h }), [landmarks, groups, w, h])

  const [state, setState] = useState<EditorState>(initial.state)
  const [placed, setPlaced] = useState<Set<string>>(() => new Set(initial.loaded))
  const [activeId, setActiveId] = useState<string>(groups[0].points[0].id)
  const [symmetry, setSymmetry] = useState(false)
  const [step, setStep] = useState<1 | 5>(1)
  const [k, setK] = useState(1) // image px per screen px
  const [loupeW, setLoupeW] = useState(0)

  const svgRef = useRef<SVGSVGElement>(null)
  const loupeRef = useRef<HTMLDivElement>(null)
  const drag = useRef<Drag | null>(null)

  useEffect(() => {
    setState(initial.state)
    setPlaced(new Set(initial.loaded))
  }, [initial])

  useEffect(() => {
    onChange?.(toLandmarks(landmarks, state, groups))
  }, [state, landmarks, groups, onChange])

  // Track the on-screen scale so dots, labels and the loupe keep a constant screen size.
  useEffect(() => {
    const svg = svgRef.current, loupe = loupeRef.current
    if (!svg || !loupe) return
    const measure = () => {
      const m = svg.getScreenCTM()
      if (m && m.a > 0) setK(1 / m.a)
      setLoupeW(loupe.clientWidth)
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(svg)
    ro.observe(loupe)
    return () => ro.disconnect()
  }, [])

  const b = { w, h }
  const total = groups.reduce((n, g) => n + g.points.length, 0)
  const save = saveState(placed.size, total)
  const active = findPoint(groups, activeId) ?? { group: groups[0], point: groups[0].points[0] }
  const ax = state.xs[active.point.id]
  const ay = state.ys[active.group.id]

  const markPlaced = (pointId: string) => {
    const hit = findPoint(groups, pointId)
    setPlaced((prev) => {
      const next = new Set(prev).add(pointId)
      if (symmetry && hit?.point.mirror) next.add(hit.point.mirror)
      return next
    })
  }

  const nudge = (dx: number, dy: number) => {
    setState((s) => nudgePoint(s, groups, active.point.id, dx, dy, b, symmetry, rules))
    markPlaced(active.point.id)
  }

  const toImage = (e: ReactPointerEvent) => {
    const m = svgRef.current?.getScreenCTM()
    if (!m) return null
    return new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse())
  }

  const onPointDown = (e: ReactPointerEvent, pointId: string, groupId: string) => {
    const p = toImage(e)
    if (!p || !svgRef.current) return
    e.preventDefault()
    svgRef.current.setPointerCapture(e.pointerId)
    drag.current = {
      id: pointId, pointerId: e.pointerId,
      offX: state.xs[pointId] - p.x, offY: state.ys[groupId] - p.y,
    }
    setActiveId(pointId)
  }

  const onPointerMove = (e: ReactPointerEvent) => {
    const d = drag.current
    if (!d || d.pointerId !== e.pointerId) return
    const p = toImage(e)
    if (!p) return
    setState((s) => movePoint(s, groups, d.id, p.x + d.offX, p.y + d.offY, b, symmetry, rules))
    markPlaced(d.id)
  }

  const endDrag = (e: ReactPointerEvent) => {
    if (drag.current?.pointerId !== e.pointerId) return
    drag.current = null
    if (svgRef.current?.hasPointerCapture(e.pointerId)) svgRef.current.releasePointerCapture(e.pointerId)
  }

  const onKeyDown = (e: KeyboardEvent) => {
    const dir = ARROWS[e.key]
    if (!dir) return
    e.preventDefault()
    const s = e.shiftKey ? 5 : 1
    nudge(dir[0] * s, dir[1] * s)
  }

  const toggleSymmetry = () => {
    const on = !symmetry
    setSymmetry(on)
    if (on) {
      setState((s) => snapCenters(s, groups, b, rules))
      setPlaced((prev) => {
        const next = new Set(prev)
        groups.forEach((g) => g.points.forEach((p) => p.side === 'center' && next.add(p.id)))
        return next
      })
    }
  }

  const reset = () => {
    setState(initial.state)
    setPlaced(new Set(initial.loaded))
  }

  // ---------- drawing sizes (screen px * k = image px) ----------
  const pad = Math.round(Math.max(w, h) * 0.04)
  const loupeScale = LOUPE_ZOOM / k // screen px per image px inside the loupe
  const loupeHint =
    active.group.points.length === 1 ? active.point.label
      : active.group.points.length === 2
        ? `${active.point.label} · ${active.point.side === 'left' ? 'Oʻng' : 'Sol'} bilan bir Y`
        : `${active.point.label} · guruh bilan bir Y`
  const tipW = 76 * k, tipH = 28 * k
  const tipAbove = ay - 52 * k > -pad
  const tipY = tipAbove ? ay - 52 * k : ay + 24 * k

  return (
    <div className="le" onKeyDown={onKeyDown}>
      <div className="le-header">
        <div>
          <h1 className="le-title">{heading}</h1>
          {subheading && <p className="le-subtitle">{subheading}</p>}
        </div>
        <div className={`le-count ${placed.size === total ? 'is-done' : ''}`}>
          {placed.size} / {total} nuqta
        </div>
      </div>

      <div className="le-body">
        <div
          className="le-stage"
          tabIndex={0}
          aria-label="Belgi nuqtalari maydoni. Strelkalar bilan faol nuqtani suring."
        >
          <svg
            ref={svgRef}
            viewBox={`${-pad} ${-pad} ${w + 2 * pad} ${h + 2 * pad}`}
            className="le-svg"
            onPointerMove={onPointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            role="group"
            aria-label={imageAlt}
          >
            <rect x={-pad} y={-pad} width={w + 2 * pad} height={h + 2 * pad} className="le-stage-bg" />
            <image href={imageUrl} x={0} y={0} width={w} height={h} className="le-image" />
            <line
              x1={axisX(b)} x2={axisX(b)} y1={-pad} y2={h + pad}
              stroke="#8A93A3" strokeOpacity={0.6} strokeWidth={k} strokeDasharray={`${4 * k} ${4 * k}`}
            />

            {groups.map((g) => {
              const sel = g.id === active.group.id
              const xs = g.points.map((p) => state.xs[p.id])
              const y = state.ys[g.id]
              const x1 = g.points.length > 1 ? Math.min(...xs) : xs[0] - 40 * k
              const x2 = g.points.length > 1 ? Math.max(...xs) : xs[0] + 40 * k
              const chipW = (g.name.length * 7.4 + 34) * k
              return (
                <g key={g.id} opacity={sel ? 1 : 0.5} pointerEvents="none">
                  {sel && <line x1={x1} x2={x2} y1={y} y2={y} stroke={hexA(g.deep, 0.22)} strokeWidth={15 * k} strokeLinecap="round" />}
                  <line x1={x1} x2={x2} y1={y} y2={y} stroke={g.deep} strokeWidth={(sel ? 5 : 2) * k} strokeLinecap="round" />
                  <rect
                    x={-pad + 8 * k} y={y - 13 * k} width={chipW} height={26 * k} rx={13 * k}
                    fill="#0B1626" stroke={sel ? g.deep : '#0B1626'} strokeWidth={2 * k}
                  />
                  <circle cx={-pad + 22 * k} cy={y} r={4 * k} fill={g.light} />
                  <text x={-pad + 32 * k} y={y + 4 * k} fontSize={12 * k} fontWeight={600} fill="#FFFFFF">{g.name}</text>
                </g>
              )
            })}

            {groups.map((g) => g.points.map((p) => {
              const sel = g.id === active.group.id
              const isActive = p.id === active.point.id
              const r = (sel ? 13 : 8) * k
              const cx = state.xs[p.id], cy = state.ys[g.id]
              return (
                <g
                  key={p.id}
                  className="le-point"
                  tabIndex={0}
                  role="button"
                  aria-label={`${p.label}: X ${cx}, Y ${cy}`}
                  aria-pressed={isActive}
                  onFocus={() => setActiveId(p.id)}
                  onPointerDown={(e) => onPointDown(e, p.id, g.id)}
                  opacity={sel ? 1 : 0.6}
                >
                  {isActive && <circle cx={cx} cy={cy} r={r + 5 * k} fill="none" stroke={hexA(g.deep, 0.35)} strokeWidth={4 * k} />}
                  <circle cx={cx} cy={cy} r={r + 1.5 * k} fill="#0B1626" />
                  <circle cx={cx} cy={cy} r={r} fill={g.deep} stroke="#FFFFFF" strokeWidth={3 * k} />
                  <circle cx={cx} cy={cy} r={Math.max(r, 22 * k)} fill="transparent" />
                </g>
              )
            }))}

            <g pointerEvents="none">
              <rect x={ax - tipW / 2} y={tipY} width={tipW} height={tipH} rx={8 * k} fill="#0B1626" />
              <text x={ax} y={tipY + tipH / 2 + 4 * k} fontSize={12 * k} fontWeight={600} fill="#FFFFFF" textAnchor="middle" className="le-num">
                {ax}, {ay}
              </text>
            </g>
          </svg>
        </div>

        <div className="le-panel">
          <div className="le-chips">
            {groups.map((g) => (
              <button
                key={g.id}
                type="button"
                className="le-chip"
                aria-pressed={g.id === active.group.id}
                onClick={() => setActiveId(g.points[0].id)}
              >
                <span className="le-dot" style={{ background: g.light }} />
                {g.name}
              </button>
            ))}
          </div>

          {hintFor(active.group.id) && (
            <p className="le-def" role="note">{hintFor(active.group.id)}</p>
          )}

          <div
            ref={loupeRef}
            className="le-loupe"
            role="img"
            aria-label={`${active.point.label} nuqtasining 3 barobar kattalashtirilgan koʻrinishi`}
            style={{
              height: LOUPE_H,
              backgroundImage: `url(${JSON.stringify(imageUrl)})`,
              backgroundSize: `${w * loupeScale}px ${h * loupeScale}px`,
              backgroundPosition: `${loupeW / 2 - ax * loupeScale}px ${LOUPE_H / 2 - ay * loupeScale}px`,
            }}
          >
            <div className="le-loupe-h" style={{ borderColor: active.group.deep }} />
            <div className="le-loupe-v" style={{ borderColor: active.group.deep }} />
            <div className="le-loupe-dot" style={{ background: active.group.deep }} />
            <span className="le-tag le-tag-top">3×</span>
            <span className="le-tag le-tag-bottom">{loupeHint}</span>
          </div>

          <div className="le-controls">
            <div className="le-pad">
              <span />
              <button type="button" className="le-arrow" aria-label="Yuqoriga" onClick={() => nudge(0, -step)}>
                <Chevron d="M6 15l6-6 6 6" />
              </button>
              <span />
              <button type="button" className="le-arrow" aria-label="Chapga" onClick={() => nudge(-step, 0)}>
                <Chevron d="M15 6l-6 6 6 6" />
              </button>
              <span />
              <button type="button" className="le-arrow" aria-label="Oʻngga" onClick={() => nudge(step, 0)}>
                <Chevron d="M9 6l6 6-6 6" />
              </button>
              <span />
              <button type="button" className="le-arrow" aria-label="Pastga" onClick={() => nudge(0, step)}>
                <Chevron d="M6 9l6 6 6-6" />
              </button>
              <span />
            </div>
            <div className="le-readouts">
              <div className="le-xy">
                <div className="le-field"><span>X</span><span className="le-num">{ax}</span></div>
                <div className="le-field"><span>Y</span><span className="le-num">{ay}</span></div>
              </div>
              <div className="le-segment" role="group" aria-label="Surish qadami">
                {([1, 5] as const).map((s) => (
                  <button key={s} type="button" aria-pressed={step === s} onClick={() => setStep(s)}>
                    {s} px
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="le-toggle">
            <span>Markaz boʻyicha simmetriya</span>
            <button
              type="button"
              role="switch"
              aria-checked={symmetry}
              aria-label="Markaz boʻyicha simmetriya"
              className="le-switch"
              onClick={toggleSymmetry}
            >
              <span />
            </button>
          </div>
          <p className="le-hint">Klaviatura: strelkalar 1 px, Shift bilan 5 px.</p>
          {!save.canSave && <p className="le-hint" role="status">{save.hint}</p>}

          <div className="le-actions">
            <button type="button" className="btn btn-secondary" onClick={reset} disabled={saving}>
              Qayta oʻrnatish
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={saving || !save.canSave}
              title={save.hint || undefined}
              onClick={() => onSave(toLandmarks(landmarks, state, groups))}
            >
              {saving ? 'Saqlanmoqda…' : 'Saqlash'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Chevron({ d }: { d: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  )
}
