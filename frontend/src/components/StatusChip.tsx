interface StatusChipProps {
  status: string
}

const STATUS_MAP: Record<string, { label: string; color: string; bg: string; border: string }> = {
  queued:    { label: 'Kutilmoqda',      color: 'var(--muted)',   bg: 'var(--inset)',       border: 'var(--border)' },
  running:   { label: 'Qayta ishlash',   color: 'var(--warning)', bg: 'var(--warning-bg)',  border: 'rgba(245,184,75,.3)' },
  done:      { label: 'Tayyor',          color: 'var(--accent)',  bg: 'var(--accent-soft)', border: 'var(--accent-border)' },
  failed:    { label: 'Xato',            color: 'var(--danger)',  bg: 'var(--danger-bg)',   border: 'var(--danger-border)' },
  pending:   { label: 'Kutilmoqda',      color: 'var(--muted)',   bg: 'var(--inset)',       border: 'var(--border)' },
  approved:  { label: 'Tasdiqlandi',     color: 'var(--accent)',  bg: 'var(--accent-soft)', border: 'var(--accent-border)' },
  review:    { label: 'Tekshiruvda',     color: 'var(--warning)', bg: 'var(--warning-bg)',  border: 'rgba(245,184,75,.3)' },
  hidden:    { label: 'Yashirilgan',     color: 'var(--danger)',  bg: 'var(--danger-bg)',   border: 'var(--danger-border)' },
  private:   { label: 'Shaxsiy',        color: 'var(--muted)',   bg: 'var(--inset)',       border: 'var(--border)' },
  public:    { label: 'Ommaviy',        color: 'var(--accent)',  bg: 'var(--accent-soft)', border: 'var(--accent-border)' },
  tshirt:    { label: 'Futbolka',       color: 'var(--text-soft)', bg: 'var(--inset)',     border: 'var(--border)' },
  pants:     { label: 'Shim',           color: 'var(--text-soft)', bg: 'var(--inset)',     border: 'var(--border)' },
  preparing: { label: 'Tayyorlanmoqda', color: 'var(--warning)', bg: 'var(--warning-bg)',  border: 'rgba(245,184,75,.3)' },
  marked:    { label: 'Belgilangan',    color: 'var(--accent)',  bg: 'var(--accent-soft)', border: 'var(--accent-border)' },
  confirmed: { label: 'Nuqtalar tasdiqlangan', color: 'var(--accent)', bg: 'var(--accent-soft)', border: 'var(--accent-border)' },
  auto:      { label: 'Avtomatik aniqlangan', color: 'var(--warning)', bg: 'var(--warning-bg)', border: 'rgba(245,184,75,.3)' },
  unmarked:  { label: 'Belgilanmagan',  color: 'var(--muted)',   bg: 'var(--inset)',       border: 'var(--border)' },
}

export default function StatusChip({ status }: StatusChipProps) {
  const s = STATUS_MAP[status] ?? {
    label: status,
    color: 'var(--muted)',
    bg: 'var(--inset)',
    border: 'var(--border)',
  }

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 10px',
        borderRadius: 'var(--radius-pill)',
        fontSize: 12,
        fontWeight: 600,
        color: s.color,
        background: s.bg,
        border: `1px solid ${s.border}`,
        whiteSpace: 'nowrap',
      }}
    >
      {s.label}
    </span>
  )
}
