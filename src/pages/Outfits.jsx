import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { listOutfits } from '../api/client.js';

export default function Outfits() {
  const [outfits, setOutfits] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    listOutfits().then(data => { setOutfits(data); setLoading(false); });
  }, []);

  return (
    <div className="outfits-page">
      <h1>My Outfits</h1>
      <p className="subtitle">Your saved <em>virtual looks</em></p>

      {loading ? (
        <p style={{ color: 'var(--muted)' }}>Loading…</p>
      ) : outfits.length === 0 ? (
        <div className="empty-state">
          <p>No saved outfits yet.</p>
          <button className="btn btn-primary" onClick={() => navigate('/')}>Create your first look</button>
        </div>
      ) : (
        <div className="outfit-grid">
          {outfits.map(outfit => (
            <div
              key={outfit.id}
              className="card outfit-card"
              onClick={() => navigate(`/?outfit=${outfit.id}`)}
              role="button"
              tabIndex={0}
              onKeyDown={e => e.key === 'Enter' && navigate(`/?outfit=${outfit.id}`)}
              aria-label={`Open outfit ${outfit.name}`}
            >
              <OutfitPreview outfit={outfit} />
              <h3>{outfit.name}</h3>
              <p className="outfit-meta">
                {outfit.items?.length ?? 0} item{outfit.items?.length !== 1 ? 's' : ''} ·{' '}
                {outfit.createdAt ? new Date(outfit.createdAt).toLocaleDateString() : ''}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function OutfitPreview({ outfit }) {
  const items = outfit.items || [];
  const top = items.find(i => i.category === 'top');
  const bottom = items.find(i => i.category === 'bottom');

  return (
    <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
      {[top, bottom].map((item, idx) => (
        item ? (
          <div key={idx} style={{ flex: 1, aspectRatio: '1/1', background: 'var(--bg)', borderRadius: 10, overflow: 'hidden' }}>
            <img
              src={item.image_url}
              alt={item.name}
              style={{ width: '100%', height: '100%', objectFit: 'contain', padding: 4 }}
              onError={e => { e.target.style.display = 'none'; }}
            />
          </div>
        ) : (
          <div key={idx} style={{ flex: 1, aspectRatio: '1/1', background: 'var(--bg)', borderRadius: 10, border: '1.5px dashed var(--border)' }} />
        )
      ))}
    </div>
  );
}
