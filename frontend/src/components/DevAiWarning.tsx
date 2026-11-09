/**
 * Dev-only warning: the backend skipped the AI check for this garment (AI_DEV_BYPASS, local DEBUG only).
 * Shown wherever the garment appears, so a bypassed upload is never mistaken for a validated one.
 * The flag comes from the backend (`Garment.ai_skipped`); the frontend never decides it.
 */
const style = {
  color: '#1A1300',
  background: 'var(--warning)',
  border: '1px solid var(--warning)',
  fontWeight: 600,
} as const

export default function DevAiWarning({ compact = false }: { compact?: boolean }) {
  if (compact) {
    return (
      <span
        title="DEV: AI tekshiruvi oʻtkazib yuborildi, bu kiyim tekshirilmagan"
        style={{ ...style, display: 'inline-flex', alignItems: 'center', padding: '2px 8px', borderRadius: 999, fontSize: 12 }}
      >
        DEV: tekshirilmagan
      </span>
    )
  }
  return (
    <div role="alert" style={{ ...style, padding: '10px 14px', borderRadius: 'var(--radius-sm)', fontSize: 14, marginBottom: 12 }}>
      DEV: AI tekshiruvi oʻtkazib yuborildi, bu kiyim tekshirilmagan.
    </div>
  )
}
