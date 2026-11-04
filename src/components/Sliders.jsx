const SLIDER_CONFIG = {
  female: [
    { key: 'height',   label: 'Height',   min: 140, max: 195, unit: 'cm' },
    { key: 'weight',   label: 'Weight',   min: 35,  max: 120, unit: 'kg' },
    { key: 'shoulder', label: 'Shoulder', min: 28,  max: 52,  unit: 'cm' },
    { key: 'chest',    label: 'Chest',    min: 68,  max: 125, unit: 'cm' },
    { key: 'waist',    label: 'Waist',    min: 52,  max: 108, unit: 'cm' },
    { key: 'hip',      label: 'Hip',      min: 68,  max: 128, unit: 'cm' },
  ],
  male: [
    { key: 'height',   label: 'Height',   min: 155, max: 205, unit: 'cm' },
    { key: 'weight',   label: 'Weight',   min: 50,  max: 140, unit: 'kg' },
    { key: 'shoulder', label: 'Shoulder', min: 36,  max: 58,  unit: 'cm' },
    { key: 'chest',    label: 'Chest',    min: 78,  max: 135, unit: 'cm' },
    { key: 'waist',    label: 'Waist',    min: 62,  max: 118, unit: 'cm' },
    { key: 'hip',      label: 'Hip',      min: 72,  max: 120, unit: 'cm' },
  ],
};

export default function Sliders({ measurements, gender = 'female', onChange }) {
  const config = SLIDER_CONFIG[gender] ?? SLIDER_CONFIG.female;

  return (
    <div>
      {config.map(({ key, label, min, max, unit }) => {
        const value = measurements[key] ?? min;
        const clamped = Math.min(Math.max(value, min), max);
        const pct = ((clamped - min) / (max - min)) * 100;
        const trackStyle = {
          background: `linear-gradient(to right, #E0529C ${pct}%, #EBD3E0 ${pct}%)`,
        };
        return (
          <div className="slider-row" key={key}>
            <span className="slider-label">{label}</span>
            <input
              type="range"
              className="slider"
              min={min}
              max={max}
              value={clamped}
              style={trackStyle}
              onChange={e => onChange({ ...measurements, [key]: Number(e.target.value) })}
              aria-label={label}
            />
            <span className="slider-value">{clamped}{unit}</span>
          </div>
        );
      })}
    </div>
  );
}
