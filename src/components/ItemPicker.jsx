import { useState } from 'react';

export default function ItemPicker({ items, selectedItems, onToggle }) {
  const [tab, setTab] = useState('top');

  const filtered = items.filter(i => i.category === tab);
  const selectedIds = new Set(selectedItems.map(i => i.id));

  return (
    <div>
      <div className="tab-row">
        <button className={`tab-chip${tab === 'top' ? ' active' : ''}`} onClick={() => setTab('top')}>Tops</button>
        <button className={`tab-chip${tab === 'bottom' ? ' active' : ''}`} onClick={() => setTab('bottom')}>Bottoms</button>
      </div>
      <div className="item-grid">
        {filtered.map(item => {
          const isSelected = selectedIds.has(item.id);
          const isDataUri = item.image_url.startsWith('data:');
          return (
            <div
              key={item.id}
              className={`item-card${isSelected ? ' selected' : ''}`}
              onClick={() => onToggle(item)}
              role="button"
              tabIndex={0}
              onKeyDown={e => e.key === 'Enter' && onToggle(item)}
              aria-pressed={isSelected}
              aria-label={item.name}
            >
              {isDataUri ? (
                <img src={item.image_url} alt={item.name} />
              ) : (
                <img
                  src={item.image_url}
                  alt={item.name}
                  onError={e => {
                    e.target.src = `data:image/svg+xml,${encodeURIComponent(
                      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#F6DDE9" rx="8"/><text x="50" y="55" text-anchor="middle" font-size="12" fill="#8B3FD9" font-family="sans-serif">${item.name[0]}</text></svg>`
                    )}`;
                  }}
                />
              )}
              <div className="item-name">{item.name}</div>
              {isSelected && <div className="check-badge">✓</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
