import { useRef, useState, type DragEvent, type ChangeEvent } from 'react'

interface DropzoneProps {
  onFile: (file: File) => void
  accept?: string
  label?: string
  hint?: string
}

export default function Dropzone({
  onFile,
  accept = 'image/*',
  label = 'Rasm tanlang yoki bu yerga tashlang',
  hint,
}: DropzoneProps) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) onFile(file)
  }

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) onFile(file)
  }

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={label}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        minHeight: 160,
        padding: 32,
        border: `2px dashed ${dragging ? 'var(--accent)' : 'var(--border-strong)'}`,
        borderRadius: 'var(--radius-md)',
        background: dragging ? 'var(--accent-soft)' : 'var(--inset)',
        cursor: 'pointer',
        transition: 'border-color 0.15s, background 0.15s',
        textAlign: 'center',
      }}
    >
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke="var(--muted)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        <polyline points="17 8 12 3 7 8" stroke="var(--muted)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        <line x1="12" y1="3" x2="12" y2="15" stroke="var(--muted)" strokeWidth="1.5" strokeLinecap="round"/>
      </svg>
      <span style={{ color: 'var(--text-soft)', fontSize: 14 }}>{label}</span>
      {hint && <span style={{ color: 'var(--muted)', fontSize: 12 }}>{hint}</span>}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        style={{ display: 'none' }}
        onChange={handleChange}
        aria-hidden="true"
      />
    </div>
  )
}
