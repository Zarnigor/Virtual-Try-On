import { useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { usePoll } from '../components/usePoll'
import Spinner from '../components/Spinner'

export default function BodyWaiting() {
  const navigate = useNavigate()
  const { state } = useLocation() as { state?: { jobId?: number } }
  const jobId = state?.jobId ?? null

  const { job, error } = usePoll(jobId)

  useEffect(() => {
    if (job?.status === 'done') {
      navigate('/body/confirm')
    }
  }, [job, navigate])

  if (!jobId) {
    return (
      <div className="page">
        <p style={{ color: 'var(--muted)' }}>Ish topilmadi. <a href="/body/upload">Qaytib borish</a></p>
      </div>
    )
  }

  return (
    <div
      className="page"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 400,
        gap: 24,
        textAlign: 'center',
      }}
    >
      {job?.status === 'failed' ? (
        <>
          <h2 style={{ fontSize: 22 }}>Tekshiruvdan oʻtmadi</h2>
          <p style={{ color: 'var(--danger)', maxWidth: 400 }}>
            {job.error_message || 'Rasm talablarga javob bermadi. Iltimos qayta urinib koʻring.'}
          </p>
          <a href="/body/upload" className="btn btn-primary">
            Qayta yuklash
          </a>
        </>
      ) : (
        <>
          <Spinner size={48} />
          <h2 style={{ fontSize: 22 }}>Rasm tekshirilmoqda</h2>
          <p style={{ color: 'var(--muted)', maxWidth: 360 }}>
            {job?.status === 'running'
              ? 'Rasm tekshirilmoqda va tayyorlanmoqda…'
              : 'Navbatda kutilmoqda…'}
          </p>
          {error && <p className="error-text">{error}</p>}
        </>
      )}
    </div>
  )
}
