import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import Avatar from '../components/Avatar.jsx';
import Sliders from '../components/Sliders.jsx';
import ItemPicker from '../components/ItemPicker.jsx';
import { getItems, getMeasurements, saveMeasurements, saveOutfit, getOutfit } from '../api/client.js';
import { BASE } from '../config/body.js';

function defaultMeasurements(gender) {
  const b = BASE[gender];
  return { height: b.height, weight: b.weight, shoulder: b.shoulder, chest: b.chest, waist: b.waist, hip: b.hip };
}

const STEPS = ['Measurements', 'Outfit', 'Save'];

export default function Editor() {
  const [gender, setGender] = useState('female');
  const [measurements, setMeasurements] = useState(() => defaultMeasurements('female'));
  const [items, setItems] = useState([]);
  const [selectedItems, setSelectedItems] = useState([]);
  const [step, setStep] = useState(0);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [outfitName, setOutfitName] = useState('');
  const [saveStatus, setSaveStatus] = useState('');
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  useEffect(() => {
    getItems().then(setItems);
    getMeasurements().then(m => {
      if (!m) return;
      const g = m.gender || 'female';
      setGender(g);
      const { gender: _g, ...rest } = m;
      setMeasurements({ ...defaultMeasurements(g), ...rest });
    });
    const outfitId = searchParams.get('outfit');
    if (outfitId) {
      getOutfit(outfitId).then(outfit => {
        if (!outfit) return;
        if (outfit.gender) setGender(outfit.gender);
        if (outfit.measurements) {
          const g = outfit.gender || 'female';
          const { gender: _g, ...rest } = outfit.measurements;
          setMeasurements({ ...defaultMeasurements(g), ...rest });
        }
        if (outfit.items) setSelectedItems(outfit.items);
        if (outfit.name) setOutfitName(outfit.name);
      });
    }
  }, []);

  function handleGenderSwitch(g) {
    if (g === gender) return;
    setGender(g);
    setMeasurements(defaultMeasurements(g));
    // Clear items that don't match the new gender
    setSelectedItems(prev => prev.filter(i => i.gender === g || i.gender === 'unisex'));
  }

  function handleToggleItem(item) {
    setSelectedItems(prev => {
      const exists = prev.find(i => i.id === item.id);
      if (exists) return prev.filter(i => i.id !== item.id);
      const otherCategory = prev.filter(i => i.category !== item.category);
      return [...otherCategory, item];
    });
  }

  async function handleSaveMeasurements() {
    await saveMeasurements({ ...measurements, gender });
    setStep(1);
  }

  async function handleSaveOutfit() {
    if (!outfitName.trim()) return;
    setSaveStatus('saving');
    await saveOutfit({
      id: searchParams.get('outfit') || crypto.randomUUID(),
      name: outfitName.trim(),
      gender,
      measurements: { ...measurements, gender },
      items: selectedItems,
    });
    setSaveStatus('saved');
    setShowSaveModal(false);
    setStep(2);
    setTimeout(() => setSaveStatus(''), 2000);
  }

  const visibleItems = items.filter(i => i.gender === gender || i.gender === 'unisex');

  return (
    <div className="editor-page">
      <StepIndicator current={step} />
      <div className="editor-body">
        <div className="avatar-stage">
          <Avatar measurements={measurements} selectedItems={selectedItems} gender={gender} />
        </div>
        <div className="controls-panel">
          <div className="card sliders-card">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <h2 style={{ margin: 0 }}>Body measurements</h2>
              <GenderToggle value={gender} onChange={handleGenderSwitch} />
            </div>
            <Sliders measurements={measurements} gender={gender} onChange={setMeasurements} />
            <div className="save-bar">
              <span style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>Changes apply instantly</span>
              <button className="btn btn-secondary" onClick={handleSaveMeasurements}>Save &amp; next →</button>
            </div>
          </div>
          <div className="card">
            <h2 style={{ marginBottom: 14 }}>Choose outfit</h2>
            {items.length === 0
              ? <p style={{ color: 'var(--muted)', fontSize: '0.875rem' }}>Loading items…</p>
              : <ItemPicker items={visibleItems} selectedItems={selectedItems} onToggle={handleToggleItem} />
            }
            <div className="save-bar" style={{ marginTop: 10 }}>
              <span style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>
                {selectedItems.length === 0 ? 'No items selected' : `${selectedItems.length} item${selectedItems.length > 1 ? 's' : ''} selected`}
              </span>
              <button
                className="btn btn-primary"
                onClick={() => { setShowSaveModal(true); if (step < 2) setStep(2); }}
                disabled={selectedItems.length === 0}
              >
                Save outfit
              </button>
            </div>
          </div>
          {saveStatus === 'saved' && (
            <div style={{ padding: '10px 16px', background: 'var(--chip-bg)', borderRadius: 12, fontSize: '0.875rem', color: 'var(--purple)', textAlign: 'center' }}>
              Outfit saved!{' '}
              <button className="btn btn-secondary" style={{ marginLeft: 8, padding: '4px 14px', fontSize: '0.8rem' }} onClick={() => navigate('/outfits')}>
                View outfits
              </button>
            </div>
          )}
        </div>
      </div>

      {showSaveModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowSaveModal(false)}>
          <div className="modal-box">
            <h2>Name your outfit</h2>
            <input
              className="input"
              placeholder="e.g. Summer look"
              value={outfitName}
              onChange={e => setOutfitName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSaveOutfit()}
              autoFocus
            />
            <div className="modal-actions">
              <button className="btn btn-secondary" onClick={() => setShowSaveModal(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={handleSaveOutfit} disabled={!outfitName.trim() || saveStatus === 'saving'}>
                {saveStatus === 'saving' ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function GenderToggle({ value, onChange }) {
  return (
    <div style={{ display: 'flex', gap: 4, background: 'var(--bg)', borderRadius: 999, padding: 3, border: '1px solid var(--border)' }}>
      {['female', 'male'].map(g => (
        <button
          key={g}
          onClick={() => onChange(g)}
          style={{
            padding: '5px 14px',
            borderRadius: 999,
            border: 'none',
            fontSize: '0.8rem',
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'background 150ms, color 150ms',
            background: value === g ? 'var(--grad)' : 'transparent',
            color: value === g ? 'white' : 'var(--muted)',
            fontFamily: 'inherit',
          }}
          aria-pressed={value === g}
        >
          {g === 'female' ? 'Female' : 'Male'}
        </button>
      ))}
    </div>
  );
}

function StepIndicator({ current }) {
  return (
    <div className="step-indicator">
      {STEPS.map((label, i) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center' }}>
          <div className={`step${i === current ? ' active' : i < current ? ' done' : ''}`}>
            <div className="step-dot">{i < current ? '✓' : i + 1}</div>
            <span style={{ marginLeft: 5 }}>{label}</span>
          </div>
          {i < STEPS.length - 1 && <div className="step-line" style={{ margin: '0 6px' }} />}
        </div>
      ))}
    </div>
  );
}
