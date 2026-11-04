import { computeFit, itemTransform } from '../lib/fit.js';
import { BASE, REGION } from '../config/body.js';

const SKIN = '#E8C4A0';
const SKIN_DARK = '#C8956A';
const SKIN_SHADOW = '#D4A882';

export default function Avatar({ measurements, selectedItems, gender = 'female' }) {
  const base = BASE[gender];
  const regionGeom = REGION[gender];
  const fit = computeFit(measurements, base);
  const { torsoScaleX, legsScaleX, scaleY, shoulderScale } = fit;

  const bodyTransform = `translate(300,600) scale(1,${scaleY}) translate(-300,-600)`;

  return (
    <svg viewBox="0 0 600 1200" xmlns="http://www.w3.org/2000/svg" aria-label={`${gender} avatar`}>
      <defs>
        <radialGradient id="skinGrad" cx="50%" cy="40%" r="60%">
          <stop offset="0%" stopColor={SKIN} />
          <stop offset="100%" stopColor={SKIN_SHADOW} />
        </radialGradient>
        <radialGradient id="faceGrad" cx="50%" cy="35%" r="55%">
          <stop offset="0%" stopColor="#F0CCAA" />
          <stop offset="100%" stopColor={SKIN_DARK} />
        </radialGradient>
      </defs>

      <g transform={bodyTransform}>
        {gender === 'female'
          ? <FemaleBody torsoScaleX={torsoScaleX} legsScaleX={legsScaleX} shoulderScale={shoulderScale} />
          : <MaleBody   torsoScaleX={torsoScaleX} legsScaleX={legsScaleX} shoulderScale={shoulderScale} />
        }
      </g>

      {selectedItems
        .slice()
        .sort((a, b) => (a.z_index || 0) - (b.z_index || 0))
        .map(item => {
          const p = item.placement;
          return (
            <g key={item.id} transform={itemTransform(item.region, fit, regionGeom)}>
              {p ? (
                <image
                  href={item.image_url}
                  x={p.x} y={p.y}
                  width={p.width} height={p.height}
                  preserveAspectRatio="xMidYMid meet"
                  onError={e => { e.target.style.display = 'none'; }}
                />
              ) : (
                <image
                  href={item.image_url}
                  x="0" y="0"
                  width="600" height="1200"
                  preserveAspectRatio="xMidYMid meet"
                  onError={e => { e.target.style.display = 'none'; }}
                />
              )}
            </g>
          );
        })}
    </svg>
  );
}

function FemaleBody({ torsoScaleX, legsScaleX, shoulderScale }) {
  const shoulderW = 68 * shoulderScale;
  const torsoW = 50 * torsoScaleX;
  const hipW = 62 * legsScaleX;

  return (
    <>
      {/* Neck */}
      <rect x="286" y="197" width="28" height="58" rx="11" fill="url(#skinGrad)" />

      {/* Head */}
      <ellipse cx="300" cy="158" rx="50" ry="58" fill="url(#faceGrad)" />
      {/* Long hair */}
      <ellipse cx="300" cy="116" rx="52" ry="30" fill="#3A2A1A" />
      <path d="M250 138 Q245 100 262 78 Q280 50 300 48 Q320 50 338 78 Q355 100 350 138" fill="#3A2A1A" />
      <path d="M250 140 Q238 200 242 300" stroke="#3A2A1A" strokeWidth="22" fill="none" strokeLinecap="round" />
      <path d="M350 140 Q362 200 358 300" stroke="#3A2A1A" strokeWidth="22" fill="none" strokeLinecap="round" />
      {/* Face */}
      <ellipse cx="285" cy="160" rx="6" ry="7" fill="white" />
      <ellipse cx="315" cy="160" rx="6" ry="7" fill="white" />
      <circle cx="285" cy="161" r="3.5" fill="#3A2510" />
      <circle cx="315" cy="161" r="3.5" fill="#3A2510" />
      <path d="M291 176 Q300 183 309 176" stroke={SKIN_DARK} strokeWidth="1.5" fill="none" strokeLinecap="round" />
      <ellipse cx="285" cy="174" rx="5" ry="2.5" fill="rgba(224,82,156,0.2)" />
      <ellipse cx="315" cy="174" rx="5" ry="2.5" fill="rgba(224,82,156,0.2)" />

      {/* Torso */}
      <g transform={`translate(300,420) scale(${torsoScaleX},1) translate(-300,-420)`}>
        <path
          d={`M${300 - shoulderW} 255 Q${300 - shoulderW - 18} 262 ${300 - shoulderW - 12} 355 L${300 - torsoW} 540 L${300 + torsoW} 540 L${300 + shoulderW + 12} 355 Q${300 + shoulderW + 18} 262 ${300 + shoulderW} 255 Z`}
          fill="url(#skinGrad)"
        />
        {/* Left arm */}
        <path
          d={`M${300 - shoulderW - 10} 265 Q${300 - shoulderW - 44} 325 ${300 - shoulderW - 36} 460 L${300 - shoulderW - 14} 460 Q${300 - shoulderW - 20} 332 ${300 - shoulderW + 6} 274 Z`}
          fill="url(#skinGrad)"
        />
        {/* Right arm */}
        <path
          d={`M${300 + shoulderW + 10} 265 Q${300 + shoulderW + 44} 325 ${300 + shoulderW + 36} 460 L${300 + shoulderW + 14} 460 Q${300 + shoulderW + 20} 332 ${300 + shoulderW - 6} 274 Z`}
          fill="url(#skinGrad)"
        />
        <ellipse cx={300 - shoulderW - 24} cy="466" rx="11" ry="9" fill={SKIN_DARK} />
        <ellipse cx={300 + shoulderW + 24} cy="466" rx="11" ry="9" fill={SKIN_DARK} />
      </g>

      {/* Hips / legs */}
      <g transform={`translate(300,580) scale(${legsScaleX},1) translate(-300,-580)`}>
        <path
          d={`M${300 - torsoW * torsoScaleX / legsScaleX} 540 Q${300 - hipW - 12} 572 ${300 - hipW} 602 L${300 + hipW} 602 Q${300 + hipW + 12} 572 ${300 + torsoW * torsoScaleX / legsScaleX} 540 Z`}
          fill={SKIN_SHADOW}
        />
        <path d={`M${300 - hipW} 602 Q${300 - hipW + 2} 800 ${300 - hipW + 8} 1182 L${300 - 14} 1182 Q${300 - 20} 800 ${300 - 10} 602 Z`} fill="url(#skinGrad)" />
        <path d={`M${300 + 10} 602 Q${300 + 20} 800 ${300 + 14} 1182 L${300 + hipW - 8} 1182 Q${300 + hipW - 2} 800 ${300 + hipW} 602 Z`} fill="url(#skinGrad)" />
        <ellipse cx={300 - hipW / 2 + 2} cy="1189" rx="20" ry="9" fill={SKIN_DARK} />
        <ellipse cx={300 + hipW / 2 - 2} cy="1189" rx="20" ry="9" fill={SKIN_DARK} />
      </g>
    </>
  );
}

function MaleBody({ torsoScaleX, legsScaleX, shoulderScale }) {
  const shoulderW = 88 * shoulderScale;
  const torsoW = 58 * torsoScaleX;
  const hipW = 50 * legsScaleX;

  return (
    <>
      {/* Neck – wider */}
      <rect x="282" y="195" width="36" height="56" rx="12" fill="url(#skinGrad)" />

      {/* Head */}
      <ellipse cx="300" cy="156" rx="52" ry="56" fill="url(#faceGrad)" />
      {/* Short hair */}
      <path d="M248 134 Q250 90 270 70 Q285 52 300 50 Q315 52 330 70 Q350 90 352 134 Q340 115 300 112 Q260 115 248 134 Z" fill="#2E1F10" />
      {/* Face */}
      <ellipse cx="284" cy="160" rx="6" ry="7" fill="white" />
      <ellipse cx="316" cy="160" rx="6" ry="7" fill="white" />
      <circle cx="284" cy="161" r="3.5" fill="#2A1E0E" />
      <circle cx="316" cy="161" r="3.5" fill="#2A1E0E" />
      {/* Stronger brow */}
      <path d="M278 148 Q284 145 292 148" stroke="#2E1F10" strokeWidth="2.5" fill="none" strokeLinecap="round" />
      <path d="M308 148 Q316 145 322 148" stroke="#2E1F10" strokeWidth="2.5" fill="none" strokeLinecap="round" />
      <path d="M290 177 Q300 182 310 177" stroke={SKIN_DARK} strokeWidth="1.5" fill="none" strokeLinecap="round" />
      {/* Stubble hint */}
      <ellipse cx="300" cy="184" rx="22" ry="8" fill="rgba(100,80,50,0.07)" />

      {/* Torso – broader shoulders, less waist taper */}
      <g transform={`translate(300,415) scale(${torsoScaleX},1) translate(-300,-415)`}>
        <path
          d={`M${300 - shoulderW} 252 Q${300 - shoulderW - 10} 258 ${300 - shoulderW - 8} 350 L${300 - torsoW} 540 L${300 + torsoW} 540 L${300 + shoulderW + 8} 350 Q${300 + shoulderW + 10} 258 ${300 + shoulderW} 252 Z`}
          fill="url(#skinGrad)"
        />
        {/* Left arm – thicker */}
        <path
          d={`M${300 - shoulderW - 6} 262 Q${300 - shoulderW - 52} 328 ${300 - shoulderW - 44} 462 L${300 - shoulderW - 16} 462 Q${300 - shoulderW - 22} 335 ${300 - shoulderW + 10} 270 Z`}
          fill="url(#skinGrad)"
        />
        {/* Right arm – thicker */}
        <path
          d={`M${300 + shoulderW + 6} 262 Q${300 + shoulderW + 52} 328 ${300 + shoulderW + 44} 462 L${300 + shoulderW + 16} 462 Q${300 + shoulderW + 22} 335 ${300 + shoulderW - 10} 270 Z`}
          fill="url(#skinGrad)"
        />
        <ellipse cx={300 - shoulderW - 30} cy="468" rx="13" ry="11" fill={SKIN_DARK} />
        <ellipse cx={300 + shoulderW + 30} cy="468" rx="13" ry="11" fill={SKIN_DARK} />
      </g>

      {/* Hips / legs – narrower than shoulders */}
      <g transform={`translate(300,575) scale(${legsScaleX},1) translate(-300,-575)`}>
        <path
          d={`M${300 - torsoW * torsoScaleX / legsScaleX} 540 Q${300 - hipW - 6} 568 ${300 - hipW} 595 L${300 + hipW} 595 Q${300 + hipW + 6} 568 ${300 + torsoW * torsoScaleX / legsScaleX} 540 Z`}
          fill={SKIN_SHADOW}
        />
        {/* Left leg */}
        <path d={`M${300 - hipW} 595 Q${300 - hipW - 2} 800 ${300 - hipW + 6} 1182 L${300 - 16} 1182 Q${300 - 22} 800 ${300 - 10} 595 Z`} fill="url(#skinGrad)" />
        {/* Right leg */}
        <path d={`M${300 + 10} 595 Q${300 + 22} 800 ${300 + 16} 1182 L${300 + hipW - 6} 1182 Q${300 + hipW + 2} 800 ${300 + hipW} 595 Z`} fill="url(#skinGrad)" />
        <ellipse cx={300 - hipW / 2 + 2} cy="1188" rx="22" ry="10" fill={SKIN_DARK} />
        <ellipse cx={300 + hipW / 2 - 2} cy="1188" rx="22" ry="10" fill={SKIN_DARK} />
      </g>
    </>
  );
}
