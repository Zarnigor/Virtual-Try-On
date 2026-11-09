import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getGarment, updateLandmarks, type Garment } from '../api/garments'
import type { GarmentLandmarks } from '../api/types'
import Spinner from '../components/Spinner'

// Landmark dot definition
interface Dot {
  key: string   // unique dot key e.g. "shoulder.left_x"
  label: string
  color: string
  x: number    // pixel coords on the ORIGINAL garment image
  y: number
}

type LandmarkMap = Record<string, Record<string, number>>

// For tshirt: shoulder(left_x, right_x, y), chest, waist, hem, sleeve_end.left(x,y), sleeve_end.right(x,y)
// For pants:  waist(left_x, right_x, y, center_x), hip, crotch(y), knee.left_leg(left_x,right_x,y), knee.right_leg, hem.left_leg, hem.right_leg
function buildDots(type: string, lm: LandmarkMap, w: number, h: number): Dot[] {
  const cx = w / 2

  const rows: Array<{ key: string; label: string; color: string; ix: string; iy: string; defX: number; defY: number }> = type === 'tshirt'
    ? [
        { key: 'shoulder.left_x',      label: 'Yelka-Sol',      color: '#FFA23D', ix: 'shoulder.left_x',  iy: 'shoulder.y',    defX: cx * 0.5, defY: h * 0.1 },
        { key: 'shoulder.right_x',     label: 'Yelka-Oʻng',     color: '#FFA23D', ix: 'shoulder.right_x', iy: 'shoulder.y',    defX: cx * 1.5, defY: h * 0.1 },
        { key: 'chest.left_x',         label: 'Koʻkrak-Sol',    color: '#FF5C7A', ix: 'chest.left_x',     iy: 'chest.y',       defX: cx * 0.6, defY: h * 0.25 },
        { key: 'chest.right_x',        label: 'Koʻkrak-Oʻng',   color: '#FF5C7A', ix: 'chest.right_x',    iy: 'chest.y',       defX: cx * 1.4, defY: h * 0.25 },
        { key: 'waist.left_x',         label: 'Bel-Sol',        color: '#3DDC84', ix: 'waist.left_x',     iy: 'waist.y',       defX: cx * 0.65, defY: h * 0.5 },
        { key: 'waist.right_x',        label: 'Bel-Oʻng',       color: '#3DDC84', ix: 'waist.right_x',    iy: 'waist.y',       defX: cx * 1.35, defY: h * 0.5 },
        { key: 'hem.left_x',           label: 'Pastki-Sol',     color: '#5C9DFF', ix: 'hem.left_x',       iy: 'hem.y',         defX: cx * 0.65, defY: h * 0.9 },
        { key: 'hem.right_x',          label: 'Pastki-Oʻng',    color: '#5C9DFF', ix: 'hem.right_x',      iy: 'hem.y',         defX: cx * 1.35, defY: h * 0.9 },
        { key: 'sleeve_end.left.x',    label: 'Yeng-Sol',       color: '#B77CFF', ix: 'sleeve_end.left.x', iy: 'sleeve_end.left.y',  defX: cx * 0.1, defY: h * 0.3 },
        { key: 'sleeve_end.right.x',   label: 'Yeng-Oʻng',      color: '#B77CFF', ix: 'sleeve_end.right.x', iy: 'sleeve_end.right.y', defX: cx * 1.9, defY: h * 0.3 },
      ]
    : [
        { key: 'waist.left_x',         label: 'Bel-Sol',        color: '#3DDC84', ix: 'waist.left_x',     iy: 'waist.y',       defX: cx * 0.5,  defY: h * 0.05 },
        { key: 'waist.right_x',        label: 'Bel-Oʻng',       color: '#3DDC84', ix: 'waist.right_x',    iy: 'waist.y',       defX: cx * 1.5,  defY: h * 0.05 },
        { key: 'waist.center_x',       label: 'Bel-Markaz',     color: '#3DDC84', ix: 'waist.center_x',   iy: 'waist.y',       defX: cx,        defY: h * 0.05 },
        { key: 'hip.left_x',           label: 'Son-Sol',        color: '#5C9DFF', ix: 'hip.left_x',       iy: 'hip.y',         defX: cx * 0.45, defY: h * 0.25 },
        { key: 'hip.right_x',          label: 'Son-Oʻng',       color: '#5C9DFF', ix: 'hip.right_x',      iy: 'hip.y',         defX: cx * 1.55, defY: h * 0.25 },
        { key: 'crotch.y',             label: 'Qoʻshilish',     color: '#FF5C7A', ix: 'crotch.center_x',  iy: 'crotch.y',      defX: cx,        defY: h * 0.4 },
        { key: 'knee.left_leg.left_x', label: 'Tizza-Sol-Sol',  color: '#35D0E8', ix: 'knee.left_leg.left_x',  iy: 'knee.left_leg.y',  defX: cx * 0.3, defY: h * 0.65 },
        { key: 'knee.left_leg.right_x', label: 'Tizza-Sol-Oʻng', color: '#35D0E8', ix: 'knee.left_leg.right_x', iy: 'knee.left_leg.y', defX: cx * 0.7, defY: h * 0.65 },
        { key: 'knee.right_leg.left_x', label: 'Tizza-Oʻng-Sol', color: '#35D0E8', ix: 'knee.right_leg.left_x', iy: 'knee.right_leg.y', defX: cx * 1.3, defY: h * 0.65 },
        { key: 'knee.right_leg.right_x', label: 'Tizza-Oʻng-Oʻng', color: '#35D0E8', ix: 'knee.right_leg.right_x', iy: 'knee.right_leg.y', defX: cx * 1.7, defY: h * 0.65 },
        { key: 'hem.left_leg.left_x',  label: 'Pocha-Sol-Sol',  color: '#5ED0C0', ix: 'hem.left_leg.left_x',  iy: 'hem.left_leg.y',  defX: cx * 0.35, defY: h * 0.95 },
        { key: 'hem.left_leg.right_x', label: 'Pocha-Sol-Oʻng', color: '#5ED0C0', ix: 'hem.left_leg.right_x', iy: 'hem.left_leg.y', defX: cx * 0.65, defY: h * 0.95 },
        { key: 'hem.right_leg.left_x', label: 'Pocha-Oʻng-Sol', color: '#5ED0C0', ix: 'hem.right_leg.left_x', iy: 'hem.right_leg.y', defX: cx * 1.35, defY: h * 0.95 },
        { key: 'hem.right_leg.right_x', label: 'Pocha-Oʻng-Oʻng', color: '#5ED0C0', ix: 'hem.right_leg.right_x', iy: 'hem.right_leg.y', defX: cx * 1.65, defY: h * 0.95 },
      ]

  return rows.map((r) => {
    // Look up existing value
    const parts = r.ix.split('.')
    let xVal = r.defX
    let yVal = r.defY

    // Navigate lm by parts
    const getNestedVal = (obj: LandmarkMap, path: string): number | undefined => {
      const keys = path.split('.')
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let cur: any = obj
      for (const k of keys) {
        if (cur == null) return undefined
        cur = cur[k]
      }
      return typeof cur === 'number' ? cur : undefined
    }

    const ex = getNestedVal(lm as LandmarkMap, r.ix)
    const ey = getNestedVal(lm as LandmarkMap, r.iy)
    if (ex !== undefined) xVal = ex
    if (ey !== undefined) yVal = ey

    return { key: r.key, label: r.label, color: r.color, x: xVal, y: yVal }
  })
}

// Convert flat dot array back to nested landmark object
function dotsToLandmarks(dots: Dot[], type: string): LandmarkMap {
  const lm: LandmarkMap = {}
  const set = (path: string, val: number) => {
    const parts = path.split('.')
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let cur: any = lm
    for (let i = 0; i < parts.length - 1; i++) {
      if (!cur[parts[i]]) cur[parts[i]] = {}
      cur = cur[parts[i]]
    }
    cur[parts[parts.length - 1]] = Math.round(val)
  }

  if (type === 'tshirt') {
    const get = (key: string) => dots.find((d) => d.key === key)
    const slx = get('shoulder.left_x'), srx = get('shoulder.right_x')
    const clx = get('chest.left_x'), crx = get('chest.right_x')
    const wlx = get('waist.left_x'), wrx = get('waist.right_x')
    const hlx = get('hem.left_x'), hrx = get('hem.right_x')
    const sel = get('sleeve_end.left.x'), ser = get('sleeve_end.right.x')

    if (slx && srx) { set('shoulder.left_x', slx.x); set('shoulder.right_x', srx.x); set('shoulder.y', (slx.y + srx.y) / 2) }
    if (clx && crx) { set('chest.left_x', clx.x); set('chest.right_x', crx.x); set('chest.y', (clx.y + crx.y) / 2) }
    if (wlx && wrx) { set('waist.left_x', wlx.x); set('waist.right_x', wrx.x); set('waist.y', (wlx.y + wrx.y) / 2) }
    if (hlx && hrx) { set('hem.left_x', hlx.x); set('hem.right_x', hrx.x); set('hem.y', (hlx.y + hrx.y) / 2) }
    if (sel) { set('sleeve_end.left.x', sel.x); set('sleeve_end.left.y', sel.y) }
    if (ser) { set('sleeve_end.right.x', ser.x); set('sleeve_end.right.y', ser.y) }
  } else {
    const get = (key: string) => dots.find((d) => d.key === key)
    const wlx = get('waist.left_x'), wrx = get('waist.right_x'), wcx = get('waist.center_x')
    const hlx = get('hip.left_x'), hrx = get('hip.right_x')
    const cr = get('crotch.y')
    const kll = get('knee.left_leg.left_x'), klr = get('knee.left_leg.right_x')
    const krl = get('knee.right_leg.left_x'), krr = get('knee.right_leg.right_x')
    const hll = get('hem.left_leg.left_x'), hlr = get('hem.left_leg.right_x')
    const hrl = get('hem.right_leg.left_x'), hrr = get('hem.right_leg.right_x')

    if (wlx && wrx) { set('waist.left_x', wlx.x); set('waist.right_x', wrx.x); set('waist.y', (wlx.y + wrx.y) / 2) }
    if (wcx) set('waist.center_x', wcx.x)
    if (hlx && hrx) { set('hip.left_x', hlx.x); set('hip.right_x', hrx.x); set('hip.y', (hlx.y + hrx.y) / 2) }
    // center_x is optional in the contract; old records without it load with the image-center default.
    if (cr) { set('crotch.y', cr.y); set('crotch.center_x', cr.x) }
    if (kll && klr) { set('knee.left_leg.left_x', kll.x); set('knee.left_leg.right_x', klr.x); set('knee.left_leg.y', (kll.y + klr.y) / 2); set('knee.y', (kll.y + klr.y) / 2) }
    if (krl && krr) { set('knee.right_leg.left_x', krl.x); set('knee.right_leg.right_x', krr.x); set('knee.right_leg.y', (krl.y + krr.y) / 2) }
    if (hll && hlr) { set('hem.left_leg.left_x', hll.x); set('hem.left_leg.right_x', hlr.x); set('hem.left_leg.y', (hll.y + hlr.y) / 2) }
    if (hrl && hrr) { set('hem.right_leg.left_x', hrl.x); set('hem.right_leg.right_x', hrr.x); set('hem.right_leg.y', (hrl.y + hrr.y) / 2) }
  }
  return lm
}

export default function LandmarkEditor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imgRef = useRef<HTMLImageElement | null>(null)

  const [garment, setGarment] = useState<Garment | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [dots, setDots] = useState<Dot[]>([])
  const [activeKey, setActiveKey] = useState<string | null>(null)
  const [scale, setScale] = useState(1)

  const DOT_R = 7

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const img = imgRef.current
    if (!canvas || !img) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)

    dots.forEach((d) => {
      const cx = d.x * scale
      const cy = d.y * scale

      ctx.beginPath()
      ctx.arc(cx, cy, DOT_R, 0, Math.PI * 2)
      ctx.fillStyle = d.key === activeKey ? '#fff' : d.color
      ctx.fill()
      ctx.strokeStyle = d.key === activeKey ? d.color : '#000'
      ctx.lineWidth = 2
      ctx.stroke()

      ctx.font = '11px Inter, sans-serif'
      ctx.fillStyle = '#fff'
      ctx.strokeStyle = 'rgba(0,0,0,0.6)'
      ctx.lineWidth = 3
      ctx.strokeText(d.label, cx + DOT_R + 2, cy + 4)
      ctx.fillText(d.label, cx + DOT_R + 2, cy + 4)
    })
  }, [dots, activeKey, scale])

  useEffect(() => { draw() }, [draw])

  useEffect(() => {
    if (!id) return
    getGarment(Number(id))
      .then(({ data }) => {
        setGarment(data)
        const img = new Image()
        img.crossOrigin = 'anonymous'
        img.onload = () => {
          imgRef.current = img
          const canvas = canvasRef.current
          if (!canvas) return
          // scale to fit within 500px width
          const maxW = 500
          const s = Math.min(1, maxW / img.naturalWidth)
          setScale(s)
          canvas.width = img.naturalWidth * s
          canvas.height = img.naturalHeight * s
          const initialDots = buildDots(
            data.type,
            (data.landmarks || {}) as unknown as LandmarkMap,
            img.naturalWidth,
            img.naturalHeight,
          )
          setDots(initialDots)
        }
        img.src = data.image_url || ''
      })
      .catch(() => setError('Kiyim topilmadi'))
      .finally(() => setLoading(false))
  }, [id])

  const hitTest = (px: number, py: number): string | null => {
    for (const d of [...dots].reverse()) {
      const dx = d.x * scale - px
      const dy = d.y * scale - py
      if (Math.sqrt(dx * dx + dy * dy) < DOT_R + 4) return d.key
    }
    return null
  }

  const getCanvasPos = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current!.getBoundingClientRect()
    return { px: e.clientX - rect.left, py: e.clientY - rect.top }
  }

  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const { px, py } = getCanvasPos(e)
    const hit = hitTest(px, py)
    setActiveKey(hit)
  }

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!activeKey) return
    const { px, py } = getCanvasPos(e)
    setDots((prev) =>
      prev.map((d) =>
        d.key === activeKey
          ? { ...d, x: px / scale, y: py / scale }
          : d
      )
    )
  }

  const handleMouseUp = () => setActiveKey(null)

  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (activeKey) return
    const { px, py } = getCanvasPos(e)
    const hit = hitTest(px, py)
    if (!hit && dots.length > 0) {
      // clicking empty area deselects
      setActiveKey(null)
    }
  }

  const handleSave = async () => {
    if (!id || !garment) return
    setSaving(true)
    setError('')
    setSuccess(false)
    try {
      const lm = dotsToLandmarks(dots, garment.type)
      await updateLandmarks(Number(id), lm as unknown as GarmentLandmarks)
      setSuccess(true)
      setTimeout(() => navigate('/wardrobe'), 1200)
    } catch {
      setError('Saqlashda xato')
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
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 24, gap: 16 }}>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/wardrobe')}>
          ← Orqaga
        </button>
        <h1 style={{ fontSize: 24, fontWeight: 700, flex: 1 }}>
          Belgi nuqtalarini qoʻyish
          {garment && (
            <span style={{ fontSize: 14, fontWeight: 400, color: 'var(--muted)', marginLeft: 10 }}>
              {garment.type === 'tshirt' ? 'Futbolka' : 'Shim'}
            </span>
          )}
        </h1>
        <button
          className="btn btn-primary"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? 'Saqlanmoqda…' : 'Saqlash'}
        </button>
      </div>

      {error && <p className="error-text" style={{ marginBottom: 12 }}>{error}</p>}
      {success && (
        <p style={{ color: 'var(--accent)', fontSize: 13, marginBottom: 12 }}>
          ✓ Muvaffaqiyatli saqlandi
        </p>
      )}

      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        <div>
          <div
            style={{
              background: 'var(--inset)',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border)',
              overflow: 'hidden',
              cursor: activeKey ? 'grabbing' : 'crosshair',
            }}
          >
            <canvas
              ref={canvasRef}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              onClick={handleCanvasClick}
              style={{ display: 'block' }}
            />
          </div>
          <p style={{ color: 'var(--muted)', fontSize: 12, marginTop: 8 }}>
            Nuqtalarni sudrab joylang
          </p>
        </div>

        <div style={{ flex: 1, minWidth: 200 }}>
          <div className="card" style={{ padding: 16 }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: 'var(--muted)' }}>
              Belgi nuqtalari
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {dots.map((d) => (
                <div
                  key={d.key}
                  onClick={() => setActiveKey(d.key === activeKey ? null : d.key)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 10px',
                    borderRadius: 'var(--radius-sm)',
                    background: d.key === activeKey ? 'var(--selected)' : 'transparent',
                    cursor: 'pointer',
                    transition: 'background 0.1s',
                  }}
                >
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: '50%',
                      background: d.color,
                      flexShrink: 0,
                    }}
                  />
                  <span style={{ fontSize: 12, color: 'var(--text-soft)', flex: 1 }}>{d.label}</span>
                  <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                    {Math.round(d.x)},{Math.round(d.y)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
