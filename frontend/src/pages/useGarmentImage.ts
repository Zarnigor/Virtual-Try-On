import { useEffect, useState } from 'react'
import { getGarment, type Garment } from '../api/garments'
import { garmentAlpha } from '../components/landmark-editor/garmentAlpha'
import type { AlphaInfo } from '../components/landmark-editor/neckHole'

/** Garment + its cleaned PNG size and alpha, for both garment editor steps (docs/10 screen 9). */
export function useGarmentImage(id: string | undefined) {
  const [garment, setGarment] = useState<Garment | null>(null)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const [alpha, setAlpha] = useState<AlphaInfo>({ bbox: null, area: null })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id) return
    let alive = true
    getGarment(Number(id))
      .then(({ data }) => {
        if (!alive) return
        setGarment(data)
        if (!data.image_url) {
          setError('Kiyim hali tayyorlanmoqda. Biroz kuting va sahifani yangilang.')
          setLoading(false)
          return
        }
        const img = new Image()
        img.crossOrigin = 'anonymous'
        img.onload = () => {
          if (!alive) return
          setSize({ w: img.naturalWidth, h: img.naturalHeight })
          setAlpha(garmentAlpha(img))
          setLoading(false)
        }
        img.onerror = () => {
          if (!alive) return
          setError('Kiyim rasmini yuklab boʻlmadi')
          setLoading(false)
        }
        img.src = data.image_url
      })
      .catch(() => {
        if (!alive) return
        setError('Kiyim topilmadi')
        setLoading(false)
      })
    return () => { alive = false }
  }, [id])

  return { garment, setGarment, size, alpha, loading, error, setError }
}

/** LANDMARKS_INVALID carries a short Uzbek message naming the group: show it as is. */
export function saveErrorText(err: unknown): string {
  const data = (err as { response?: { data?: { code?: string; detail?: string } } })?.response?.data
  return data?.code === 'LANDMARKS_INVALID' && data.detail ? data.detail : 'Saqlashda xato. Qayta urinib koʻring.'
}
