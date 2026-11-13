import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode } from 'react'
import {
  NO_RULES, activeRules, axisX, findPoint, fromLandmarks, movePoint, nudgePoint, requiredCount, saveState,
  snapCenters, toLandmarks, type Bounds, type EditorState, type GroupDef, type Rules,
} from './geometry'
import { hintFor } from './lineHints'
import {
  deleteVertex, insertVertex, moveVertex, withNeckHole, NECK_HOLE_MIN_POINTS, type NeckShape, type Pt,
} from './neckHole'
import { LANDMARK_EDITOR, NECK_EDITOR } from '../../locale/uz'
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
  /** Sanity checks on the current landmarks: errors block Save, warnings are only shown. */
  check?: (landmarks: Record<string, unknown>) => { errors: string[]; warnings: string[] }
  /** Visible area in image px (auto-zoom, e.g. the neck area); default = the whole image + a margin. */
  view?: { x: number; y: number; w: number; h: number }
  /** Save button text (default "Saqlash"; step 1 of a T-shirt: "Keyingi"). */
  saveLabel?: string
  /** Step indicator, e.g. "1 / 2". */
  stepLabel?: string
  /** Extra buttons in the action row, before Save (e.g. "Oʻtkazib yuborish"). */
  extraActions?: ReactNode
  /**
   * Neckline hole polygon mode (docs/09 #102): `initial` = the stored polygon (null = none). When every point of
   * `groups` is placed (and the drag is released) the hole is created ONCE from `suggest(landmarks, guess(landmarks))`
   * and then never moves by itself: moving the collar points does not touch it; the shape buttons and
   * "Qayta tiklash" rebuild it from the current points. Two edit modes so the handles never steal each other's clicks:
   * "points" (collar points) and "hole" (polygon vertices / edges). The saved landmarks carry `neck_hole: {polygon}`.
   */
  polygon?: {
    initial: Pt[] | null
    suggest: (landmarks: Record<string, unknown>, shape: NeckShape) => Pt[] | null
    guess: (landmarks: Record<string, unknown>) => NeckShape
  }
}

const LOUPE_ZOOM = 3
const LOUPE_H = 220
const ARROWS: Record<string, [number, number]> = {
  ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0],
}

interface Drag { id: string; pointerId: number; offX: number; offY: number }
interface VertexDrag { i: number; pointerId: number; offX: number; offY: number }
const HOLE = { stroke: '#D63A5A', fill: 'rgba(214, 58, 90, 0.22)' }

function hexA(hex: string, a: number) {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`
}

export default function LandmarkEditor({
  imageUrl, imageAlt, bounds, groups, rules: allRules = NO_RULES, landmarks, heading, subheading, saving, onSave,
  onChange, check, view, saveLabel, stepLabel, extraActions, polygon,
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
  const vdrag = useRef<VertexDrag | null>(null)
  // polygon mode: null = not created yet; an array = the hole (stored, suggested once, or edited)
  const [poly, setPoly] = useState<Pt[] | null>(polygon?.initial ?? null)
  const [activeVertex, setActiveVertex] = useState<number | null>(null)
  const [mode, setMode] = useState<'points' | 'hole'>(polygon?.initial ? 'hole' : 'points')
  const [shape, setShape] = useState<NeckShape | null>(null)
  const [dragging, setDragging] = useState(false)

  useEffect(() => {
    setState(initial.state)
    setPlaced(new Set(initial.loaded))
  }, [initial])

  // optional groups nobody has placed yet do not constrain moves, and are not saved
  const rules = useMemo(() => activeRules(allRules, groups, placed), [allRules, groups, placed])
  const base = useMemo(() => toLandmarks(landmarks, state, groups, placed), [landmarks, state, groups, placed])
  const allPlaced = groups.every((g) => g.points.every((p) => placed.has(p.id)))
  // create the hole once, after the last collar point is placed and released; never re-follow the points
  useEffect(() => {
    if (!polygon || poly || !allPlaced || dragging) return
    const g = polygon.guess(base)
    const next = polygon.suggest(base, g)
    if (!next) return
    setShape(g)
    setPoly(next)
    setMode('hole')
  }, [polygon, poly, allPlaced, dragging, base])
  const shown: Pt[] | null = polygon ? poly : null
  const holeMode = !!polygon && mode === 'hole' && !!shown
  const shownRef = useRef(shown)
  shownRef.current = shown
  const current = useMemo(() => (polygon ? withNeckHole(base, shown) : base), [polygon, base, shown])
  const checks = useMemo(() => (check ? check(current) : { errors: [], warnings: [] }), [check, current])

  useEffect(() => {
    onChange?.(current)
  }, [current, onChange])

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
  const req = requiredCount(groups, placed)
  const optTotal = groups.reduce((n, g) => n + (g.optional ? g.points.length : 0), 0)
  const optPlaced = placed.size - req.placed
  const save = saveState(req.placed, req.total)
  const canSave = save.canSave && checks.errors.length === 0 && (!polygon || (shown?.length ?? 0) >= NECK_HOLE_MIN_POINTS)
  const active = findPoint(groups, activeId) ?? { group: groups[0], point: groups[0].points[0] }
  const vertex = holeMode && shown && activeVertex !== null && activeVertex < shown.length ? shown[activeVertex] : null
  const ax = vertex ? vertex[0] : state.xs[active.point.id]
  const ay = vertex ? vertex[1] : state.ys[active.group.id]

  const markPlaced = (pointId: string) => {
    const hit = findPoint(groups, pointId)
    setPlaced((prev) => {
      const next = new Set(prev).add(pointId)
      if (symmetry && hit?.point.mirror) next.add(hit.point.mirror)
      return next
    })
  }

  const nudge = (dx: number, dy: number) => {
    if (vertex && activeVertex !== null && shown) {
      setPoly(moveVertex(shown, activeVertex, [vertex[0] + dx, vertex[1] + dy], w, h))
      return
    }
    setState((s) => nudgePoint(s, groups, active.point.id, dx, dy, b, symmetry, rules))
    markPlaced(active.point.id)
  }

  const removeVertex = () => {
    if (!shown || activeVertex === null || shown.length <= NECK_HOLE_MIN_POINTS) return
    setPoly(deleteVertex(shown, activeVertex))
    setActiveVertex(null)
  }

  const onVertexDown = (e: ReactPointerEvent, i: number) => {
    const p = toImage(e)
    if (!p || !svgRef.current || !shown) return
    e.preventDefault()
    e.stopPropagation()
    svgRef.current.setPointerCapture(e.pointerId)
    vdrag.current = { i, pointerId: e.pointerId, offX: shown[i][0] - p.x, offY: shown[i][1] - p.y }
    setActiveVertex(i)
  }

  /** Click on an edge: a new vertex there, selected and dragged at once. */
  const onEdgeDown = (e: ReactPointerEvent, i: number) => {
    const p = toImage(e)
    if (!p || !svgRef.current || !shown) return
    e.preventDefault()
    e.stopPropagation()
    const next = insertVertex(shown, i, [p.x, p.y])
    setPoly(next)
    svgRef.current.setPointerCapture(e.pointerId)
    vdrag.current = { i: i + 1, pointerId: e.pointerId, offX: 0, offY: 0 }
    setActiveVertex(i + 1)
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
    setDragging(true)
    setActiveId(pointId)
    setActiveVertex(null)
  }

  const onPointerMove = (e: ReactPointerEvent) => {
    const v = vdrag.current
    if (v && v.pointerId === e.pointerId) {
      const p = toImage(e)
      const cur = shownRef.current
      if (p && cur) setPoly(moveVertex(cur, v.i, [p.x + v.offX, p.y + v.offY], w, h))
      return
    }
    const d = drag.current
    if (!d || d.pointerId !== e.pointerId) return
    const p = toImage(e)
    if (!p) return
    setState((s) => movePoint(s, groups, d.id, p.x + d.offX, p.y + d.offY, b, symmetry, rules))
    markPlaced(d.id)
  }

  const endDrag = (e: ReactPointerEvent) => {
    if (vdrag.current?.pointerId === e.pointerId) {
      vdrag.current = null
      if (svgRef.current?.hasPointerCapture(e.pointerId)) svgRef.current.releasePointerCapture(e.pointerId)
      return
    }
    if (drag.current?.pointerId !== e.pointerId) return
    drag.current = null
    setDragging(false)
    if (svgRef.current?.hasPointerCapture(e.pointerId)) svgRef.current.releasePointerCapture(e.pointerId)
  }

  const onKeyDown = (e: KeyboardEvent) => {
    if ((e.key === 'Delete' || e.key === 'Backspace') && vertex) {
      e.preventDefault()
      removeVertex()
      return
    }
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
    setPoly(polygon?.initial ?? null)
    setActiveVertex(null)
  }

  /** Shape button / "Qayta tiklash": rebuild the hole from the CURRENT collar points. */
  const rebuild = (sh: NeckShape) => {
    if (!polygon) return
    const next = polygon.suggest(base, sh)
    if (!next) return
    setShape(sh)
    setPoly(next)
    setActiveVertex(null)
    setMode('hole')
  }
  const resetPolygon = () => polygon && rebuild(shape ?? polygon.guess(base))
  const toPoints = () => {
    setMode('points')
    setActiveVertex(null)
  }

  // ---------- drawing sizes (screen px * k = image px) ----------
  const pad = Math.round(Math.max(w, h) * 0.04)
  const vb = view ?? { x: -pad, y: -pad, w: w + 2 * pad, h: h + 2 * pad }
  const loupeScale = LOUPE_ZOOM / k // screen px per image px inside the loupe
  const loupeHint = vertex && activeVertex !== null ? NECK_EDITOR.vertexLabel(activeVertex)
    : active.group.points.length === 1 ? active.point.label
      : active.group.points.length === 2
        ? `${active.point.label} · ${active.point.side === 'left' ? 'Oʻng' : 'Sol'} bilan bir Y`
        : `${active.point.label} · guruh bilan bir Y`
  const tipW = 76 * k, tipH = 28 * k
  const tipAbove = ay - 52 * k > vb.y
  const tipY = tipAbove ? ay - 52 * k : ay + 24 * k

  return (
    <div className="le" onKeyDown={onKeyDown}>
      <div className="le-header">
        <div>
          <h1 className="le-title">{heading}</h1>
          {subheading && <p className="le-subtitle">{subheading}</p>}
        </div>
        {stepLabel && <span className="le-step" aria-label={`Qadam ${stepLabel}`}>{stepLabel}</span>}
        <div className={`le-count ${req.placed === req.total ? 'is-done' : ''}`}>
          {req.placed} / {req.total} nuqta
          {optTotal > 0 && <span className="le-count-opt"> {LANDMARK_EDITOR.optionalCount(optPlaced, optTotal)}</span>}
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
            viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
            className="le-svg"
            onPointerMove={onPointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            role="group"
            aria-label={imageAlt}
          >
            <rect x={vb.x} y={vb.y} width={vb.w} height={vb.h} className="le-stage-bg" />
            <image href={imageUrl} x={0} y={0} width={w} height={h} className="le-image" />
            <line
              x1={axisX(b)} x2={axisX(b)} y1={vb.y} y2={vb.y + vb.h}
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
                    x={vb.x + 8 * k} y={y - 13 * k} width={chipW} height={26 * k} rx={13 * k}
                    fill="#0B1626" stroke={sel ? g.deep : '#0B1626'} strokeWidth={2 * k}
                  />
                  <circle cx={vb.x + 22 * k} cy={y} r={4 * k} fill={g.light} />
                  <text x={vb.x + 32 * k} y={y + 4 * k} fontSize={12 * k} fontWeight={600} fill="#FFFFFF">{g.name}</text>
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
                  onFocus={() => { setActiveId(p.id); setActiveVertex(null) }}
                  onPointerDown={(e) => onPointDown(e, p.id, g.id)}
                  opacity={holeMode ? 0.35 : sel ? 1 : 0.6}
                  pointerEvents={holeMode ? 'none' : undefined}
                >
                  {isActive && <circle cx={cx} cy={cy} r={r + 5 * k} fill="none" stroke={hexA(g.deep, 0.35)} strokeWidth={4 * k} />}
                  <circle cx={cx} cy={cy} r={r + 1.5 * k} fill="#0B1626" />
                  <circle cx={cx} cy={cy} r={r} fill={g.deep} stroke="#FFFFFF" strokeWidth={3 * k} />
                  <circle cx={cx} cy={cy} r={Math.max(r, 22 * k)} fill="transparent" />
                </g>
              )
            }))}

            {shown && (
              <g className="le-hole" pointerEvents={holeMode ? undefined : 'none'} opacity={holeMode ? 1 : 0.55}>
                <polygon
                  points={shown.map(([x, y]) => `${x},${y}`).join(' ')}
                  fill={HOLE.fill} stroke={HOLE.stroke} strokeWidth={2 * k} strokeLinejoin="round" pointerEvents="none"
                />
                {shown.map((p, i) => {
                  const q = shown[(i + 1) % shown.length]
                  return (
                    <line
                      key={`e${i}`} x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} stroke="transparent" strokeWidth={14 * k}
                      className="le-hole-edge" onPointerDown={(e) => onEdgeDown(e, i)}
                    />
                  )
                })}
                {holeMode && shown.map(([x, y], i) => (
                  <g
                    key={`v${i}`} className="le-hole-vertex" tabIndex={0} role="button"
                    aria-label={`${NECK_EDITOR.vertexLabel(i)}: X ${x}, Y ${y}`} aria-pressed={i === activeVertex}
                    onFocus={() => setActiveVertex(i)} onPointerDown={(e) => onVertexDown(e, i)}
                  >
                    <circle
                      cx={x} cy={y} r={(i === activeVertex ? 8 : 6) * k}
                      fill={i === activeVertex ? HOLE.stroke : '#FFFFFF'} stroke={HOLE.stroke} strokeWidth={2 * k}
                    />
                    <circle cx={x} cy={y} r={14 * k} fill="transparent" />
                  </g>
                ))}
              </g>
            )}

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
                onClick={() => { setActiveId(g.points[0].id); toPoints() }}
              >
                <span className="le-dot" style={{ background: g.light }} />
                {g.name}
              </button>
            ))}
          </div>

          {hintFor(active.group.id) && !vertex && (
            <p className="le-def" role="note">{hintFor(active.group.id)}</p>
          )}

          {polygon && (
            <div className="le-hole-panel">
              <div className="le-hole-head">
                <strong>{NECK_EDITOR.polygonTitle}</strong>
                {shown && <span className="le-hint">{NECK_EDITOR.polygonCount(shown.length)}</span>}
              </div>
              <div className="le-segment le-mode" role="group" aria-label={NECK_EDITOR.modeLabel}>
                <button type="button" aria-pressed={!holeMode} onClick={toPoints}>{NECK_EDITOR.modePoints}</button>
                <button type="button" aria-pressed={holeMode} disabled={!shown} onClick={() => setMode('hole')}>
                  {NECK_EDITOR.modeHole}
                </button>
              </div>
              <p className="le-def" role="note">{NECK_EDITOR.polygonHint}</p>
              {shown ? (
                <>
                  <div className="le-segment le-shapes" role="group" aria-label={NECK_EDITOR.shapeLabel}>
                    {(['v', 'round', 'square'] as const).map((sh) => (
                      <button key={sh} type="button" aria-pressed={shape === sh} onClick={() => rebuild(sh)}>
                        {NECK_EDITOR.shapes[sh]}
                      </button>
                    ))}
                  </div>
                  <p className="le-hint">{holeMode ? NECK_EDITOR.polygonHelp : NECK_EDITOR.pointsModeHelp}</p>
                  <div className="le-hole-actions">
                    <button
                      type="button" className="btn btn-secondary btn-sm" onClick={removeVertex}
                      disabled={!vertex || shown.length <= NECK_HOLE_MIN_POINTS}
                    >
                      {NECK_EDITOR.deleteVertex}
                    </button>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={resetPolygon}>
                      {NECK_EDITOR.resetPolygon}
                    </button>
                  </div>
                </>
              ) : (
                <p className="le-hint" role="status">{NECK_EDITOR.polygonWaiting}</p>
              )}
            </div>
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
          {checks.errors.length > 0 && (
            <div className="le-checks is-error" role="alert">
              <strong>{LANDMARK_EDITOR.checksTitle}</strong>
              <ul>{checks.errors.map((m) => <li key={m}>{m}</li>)}</ul>
            </div>
          )}
          {checks.warnings.length > 0 && (
            <div className="le-checks is-warning" role="status">
              <strong>{LANDMARK_EDITOR.warningsTitle}</strong>
              <ul>{checks.warnings.map((m) => <li key={m}>{m}</li>)}</ul>
            </div>
          )}

          <div className="le-actions">
            <button type="button" className="btn btn-secondary" onClick={reset} disabled={saving}>
              Qayta oʻrnatish
            </button>
            {extraActions}
            <button
              type="button"
              className="btn btn-primary"
              disabled={saving || !canSave}
              title={save.hint || checks.errors[0] || undefined}
              onClick={() => onSave(current)}
            >
              {saving ? LANDMARK_EDITOR.saving : (saveLabel ?? LANDMARK_EDITOR.save)}
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
