import { useState, useRef, useEffect, useCallback } from 'react';
import { computeFit, itemTransform } from '../lib/fit.js';
import { BASE, REGION } from '../config/body.js';
import itemsData from '../mock/items.json';

const GUIDE_LINES = {
  female: [
    { label: 'Shoulders', y: 255, color: '#8B3FD9' },
    { label: 'Bust',      y: 340, color: '#E0529C' },
    { label: 'Waist',     y: 490, color: '#E0529C' },
    { label: 'Hips',      y: 600, color: '#8B3FD9' },
  ],
  male: [
    { label: 'Shoulders', y: 252, color: '#8B3FD9' },
    { label: 'Chest',     y: 340, color: '#E0529C' },
    { label: 'Waist',     y: 490, color: '#E0529C' },
    { label: 'Hips',      y: 590, color: '#8B3FD9' },
  ],
};

const DEFAULT_PLACEMENT = { x: 190, y: 240, width: 220, height: 293 };

export default function Calibrate() {
  const [gender, setGender] = useState('female');
  const [itemId, setItemId] = useState('');
  const [placement, setPlacement] = useState({ ...DEFAULT_PLACEMENT });
  const [copied, setCopied] = useState(false);
  const svgRef = useRef(null);
  const dragRef = useRef(null);

  const items = itemsData.filter(i => i.gender === gender || i.gender === 'unisex');
  const item = items.find(i => i.id === itemId) || items[0];

  // When gender or item changes, seed from item's existing placement
  useEffect(() => {
    if (item?.placement) setPlacement({ ...item.placement });
    else setPlacement({ ...DEFAULT_PLACEMENT });
  }, [item?.id]);

  const base = BASE[gender];
  const regionGeom = REGION[gender];
  const fit = computeFit(
    { height: base.height, weight: base.weight, shoulder: base.shoulder, chest: base.chest, waist: base.waist, hip: base.hip },
    base
  );

  // Convert SVG coords from mouse event
  function svgPoint(e) {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const svgP = pt.matrixTransform(svg.getScreenCTM().inverse());
    return svgP;
  }

  // Drag the image
  function onMouseDown(e) {
    e.preventDefault();
    const start = svgPoint(e);
    const orig = { ...placement };
    function onMove(ev) {
      const cur = svgPoint(ev);
      setPlacement(p => ({
        ...p,
        x: Math.round(orig.x + cur.x - start.x),
        y: Math.round(orig.y + cur.y - start.y),
      }));
    }
    function onUp() {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  // Scroll wheel → scale width (maintain aspect ratio if height known)
  function onWheel(e) {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -5 : 5;
    setPlacement(p => {
      const newW = Math.max(60, Math.min(500, p.width + delta));
      const ratio = p.height / p.width;
      return { ...p, width: newW, height: Math.round(newW * ratio) };
    });
  }

  function copyJSON() {
    const json = JSON.stringify(placement);
    navigator.clipboard.writeText(json).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }

  const transform = item ? itemTransform(item.region, fit, regionGeom) : '';

  return (
    <div style={{ display: 'flex', gap: 24, padding: '20px 24px', maxWidth: 1000, margin: '0 auto', flexWrap: 'wrap' }}>
      <div style={{ flex: '0 0 auto' }}>
        <h2 style={{ marginBottom: 14, fontFamily: 'Fraunces, serif', fontSize: '1.2rem' }}>Calibrate placement</h2>

        {/* Controls */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 4, background: 'var(--bg)', borderRadius: 999, padding: 3, border: '1px solid var(--border)' }}>
            {['female', 'male'].map(g => (
              <button key={g} onClick={() => { setGender(g); setItemId(''); }}
                style={{ padding: '5px 14px', borderRadius: 999, border: 'none', fontSize: '0.8rem', fontWeight: 600, cursor: 'pointer',
                  background: gender === g ? 'var(--grad)' : 'transparent', color: gender === g ? 'white' : 'var(--muted)', fontFamily: 'inherit' }}>
                {g === 'female' ? 'Female' : 'Male'}
              </button>
            ))}
          </div>
          <select
            value={item?.id || ''}
            onChange={e => setItemId(e.target.value)}
            className="input"
            style={{ width: 180 }}
          >
            {items.map(i => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
        </div>

        {/* Sliders */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
          {[
            { label: 'x', key: 'x', min: -100, max: 500 },
            { label: 'y', key: 'y', min: -100, max: 800 },
            { label: 'width', key: 'width', min: 60, max: 500 },
            { label: 'height', key: 'height', min: 60, max: 900 },
          ].map(({ label, key, min, max }) => (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 44, fontSize: '0.8rem', color: 'var(--muted)', fontWeight: 500 }}>{label}</span>
              <input type="range" className="slider" min={min} max={max} value={placement[key]}
                style={{ background: `linear-gradient(to right, #E0529C ${((placement[key]-min)/(max-min)*100)}%, #EBD3E0 ${((placement[key]-min)/(max-min)*100)}%)` }}
                onChange={e => setPlacement(p => ({ ...p, [key]: Number(e.target.value) }))} />
              <span style={{ width: 36, fontSize: '0.8rem', color: 'var(--purple)', fontWeight: 600, textAlign: 'right' }}>{placement[key]}</span>
            </div>
          ))}
        </div>

        {/* JSON output */}
        <div style={{ background: 'var(--bg)', borderRadius: 12, padding: '10px 14px', fontFamily: 'monospace', fontSize: '0.8rem', color: 'var(--text)', marginBottom: 10, border: '1px solid var(--border)' }}>
          {JSON.stringify(placement, null, 2)}
        </div>
        <button className="btn btn-primary" onClick={copyJSON} style={{ width: '100%' }}>
          {copied ? '✓ Copied!' : 'Copy JSON'}
        </button>

        <p style={{ marginTop: 12, fontSize: '0.78rem', color: 'var(--muted)', lineHeight: 1.5 }}>
          Drag the garment to reposition.<br />
          Scroll wheel over avatar to resize.
        </p>
      </div>

      {/* SVG preview */}
      <div style={{ flex: '1 1 300px', minWidth: 260 }}>
        <svg
          ref={svgRef}
          viewBox="0 0 600 1200"
          style={{ width: '100%', maxWidth: 340, display: 'block', borderRadius: 20, background: 'linear-gradient(180deg,#FEF0F7 0%,#F3E6FF 100%)', boxShadow: '0 4px 20px rgba(139,63,217,0.12)', cursor: 'grab' }}
          onWheel={onWheel}
        >
          {/* Guide lines */}
          {GUIDE_LINES[gender].map(gl => (
            <g key={gl.label}>
              <line x1="0" y1={gl.y} x2="600" y2={gl.y} stroke={gl.color} strokeWidth="1" strokeDasharray="8 4" opacity="0.6" />
              <text x="8" y={gl.y - 4} fontSize="18" fill={gl.color} opacity="0.8" fontFamily="sans-serif">{gl.label}</text>
            </g>
          ))}

          {/* Center line */}
          <line x1="300" y1="0" x2="300" y2="1200" stroke="#CBD0D8" strokeWidth="1" strokeDasharray="4 6" opacity="0.5" />

          {/* Garment image, draggable */}
          {item && (
            <g transform={transform}>
              <image
                href={item.image_url}
                x={placement.x} y={placement.y}
                width={placement.width} height={placement.height}
                preserveAspectRatio="xMidYMid meet"
                style={{ cursor: 'grab' }}
                onMouseDown={onMouseDown}
              />
              {/* Drag handle outline */}
              <rect
                x={placement.x} y={placement.y}
                width={placement.width} height={placement.height}
                fill="none" stroke="#8B3FD9" strokeWidth="1.5" strokeDasharray="6 3"
                style={{ cursor: 'grab', pointerEvents: 'none' }}
              />
            </g>
          )}
        </svg>
      </div>
    </div>
  );
}
