import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getStaffAvatar, saveStaffAvatarLandmarks, type StaffAvatar } from '../../api/staff'
import type { BodyLandmarks } from '../../api/types'
import Spinner from '../../components/Spinner'
import StatusChip from '../../components/StatusChip'
import LandmarkEditor from '../../components/landmark-editor/LandmarkEditor'
import { BODY_GROUPS, BODY_RULES } from '../../components/landmark-editor/bodyGroups'

/** Staff: mark an avatar's body landmarks. Saving sets landmarks_confirmed_at; the try-on engine uses them. */
export default function StaffAvatarEditor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [avatar, setAvatar] = useState<StaffAvatar | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getStaffAvatar(Number(id))
      .then(({ data }) => setAvatar(data))
      .catch(() => setError('Avatar topilmadi'))
  }, [id])

  const handleSave = async (landmarks: Record<string, unknown>) => {
    if (!avatar) return
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      const { data } = await saveStaffAvatarLandmarks(avatar.id, { landmarks: landmarks as unknown as BodyLandmarks })
      setAvatar(data)
      setSaved(true)
    } catch (err: unknown) {
      const data = (err as { response?: { data?: { code?: string; detail?: string } } })?.response?.data
      setError(data?.code === 'LANDMARKS_INVALID' && data.detail ? data.detail : 'Saqlashda xato. Qayta urinib koʻring.')
    } finally {
      setSaving(false)
    }
  }

  if (!avatar) {
    return (
      <div className="page" style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
        {error ? <p className="error-text">{error}</p> : <Spinner size={40} />}
      </div>
    )
  }

  return (
    <div className="page">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/staff/avatars')}>← Orqaga</button>
        <StatusChip status={avatar.status} />
      </div>
      {error && <p className="error-text" style={{ marginBottom: 12 }}>{error}</p>}
      {saved && <p role="status" style={{ color: 'var(--accent)', fontSize: 13, marginBottom: 12 }}>Saqlandi. Sinab koʻrish shu nuqtalardan foydalanadi.</p>}
      {avatar.image_url ? (
        <LandmarkEditor
          imageUrl={avatar.image_url}
          imageAlt="Avatar rasmi"
          bounds={{ w: 600, h: 1200 }}
          groups={BODY_GROUPS}
          rules={BODY_RULES}
          landmarks={avatar.landmarks}
          heading={`Avatar nuqtalari · ${avatar.sex === 'male' ? 'Erkak' : 'Ayol'} ${avatar.build}`}
          subheading="Har bir chiziqning chap va oʻng nuqtasini tana chetiga qoʻying."
          saving={saving}
          onSave={handleSave}
        />
      ) : (
        <p className="error-text">Avatar rasmi yoʻq.</p>
      )}
    </div>
  )
}
