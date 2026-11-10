import { useEffect, useState } from 'react'
import { getConfig } from '../api/config'

/** Header label shown only when the backend runs with DEMO_MODE=1 (precomputed try-on results). */
export default function DemoBadge() {
  const [demo, setDemo] = useState(false)
  useEffect(() => {
    getConfig().then((c) => setDemo(c.demo_mode))
  }, [])
  if (!demo) return null
  return (
    <span
      title="Demo rejimi: tanlangan avatar va kiyimlar uchun natijalar oldindan tayyorlangan."
      style={{
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: '0.08em',
        padding: '3px 8px',
        borderRadius: 999,
        color: '#1A1300', // same chip style as DevAiWarning
        background: 'var(--warning)',
        border: '1px solid var(--warning)',
      }}
    >
      DEMO
    </span>
  )
}
