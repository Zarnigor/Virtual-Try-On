import { useState, useEffect, useRef } from 'react'
import { getJob, type Job } from '../api/jobs'

export function usePoll(jobId: number | null) {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!jobId) return

    const poll = async () => {
      try {
        const { data } = await getJob(jobId)
        setJob(data)
        if (data.status === 'done' || data.status === 'failed') {
          if (intervalRef.current) clearInterval(intervalRef.current)
        }
      } catch {
        setError('Ish holatini olishda xato')
        if (intervalRef.current) clearInterval(intervalRef.current)
      }
    }

    poll()
    intervalRef.current = setInterval(poll, 2000)

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [jobId])

  return { job, error }
}
