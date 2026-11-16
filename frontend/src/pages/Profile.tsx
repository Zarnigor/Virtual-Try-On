import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { deleteAccount } from '../api/auth'
import { deleteBody, getBody, type Body } from '../api/bodies'
import { useMe } from '../components/useMe'
import { useAuthStore } from '../store/auth'
import { PROFILE_TEXT } from '../locale/uz'

/** Screen 12: profile and privacy. The owner may delete the body (with its outfits) or the whole account. */
export default function Profile() {
  const user = useMe()
  const navigate = useNavigate()
  const { logout } = useAuthStore()
  const [body, setBody] = useState<Body | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    getBody().then(({ data }) => setBody(data)).catch(() => setBody(null))
  }, [])

  const removeBody = async () => {
    if (!confirm(PROFILE_TEXT.deleteBodyConfirm)) return
    setBusy(true)
    setError('')
    try {
      await deleteBody()
      setBody(null)
      setMessage(PROFILE_TEXT.bodyDeleted)
    } catch {
      setError(PROFILE_TEXT.failed)
    } finally {
      setBusy(false)
    }
  }

  const removeAccount = async () => {
    if (!confirm(PROFILE_TEXT.deleteAccountConfirm)) return
    setBusy(true)
    setError('')
    try {
      await deleteAccount()
      logout()
      navigate('/login')
    } catch {
      setError(PROFILE_TEXT.failed)
      setBusy(false)
    }
  }

  return (
    <div className="page" style={{ maxWidth: 640 }}>
      <h1 className="page-title">{PROFILE_TEXT.title}</h1>
      {message && <p role="status" style={{ color: 'var(--accent)', fontSize: 14, marginBottom: 12 }}>{message}</p>}
      {error && <p className="error-text" style={{ marginBottom: 12 }}>{error}</p>}

      <div className="card" style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 16, marginBottom: 8 }}>{PROFILE_TEXT.account}</h2>
        <p style={{ color: 'var(--text-soft)', fontSize: 14, marginBottom: 12 }}>{user?.email ?? '…'}</p>
        <button className="btn btn-secondary btn-sm" onClick={() => { logout(); navigate('/login') }}>
          {PROFILE_TEXT.logout}
        </button>
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 16, marginBottom: 8 }}>{PROFILE_TEXT.privacy}</h2>
        <ul style={{ paddingLeft: 18, color: 'var(--text-soft)', fontSize: 14, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {PROFILE_TEXT.privacyPoints.map((p) => <li key={p}>{p}</li>)}
        </ul>
      </div>

      <div className="card" style={{ borderColor: 'var(--danger-border)' }}>
        <h2 style={{ fontSize: 16, marginBottom: 8 }}>{PROFILE_TEXT.danger}</h2>
        <p style={{ color: 'var(--text-soft)', fontSize: 14, marginBottom: 12 }}>
          {body ? PROFILE_TEXT.deleteBodyHelp : PROFILE_TEXT.noBody}
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn btn-danger btn-sm" onClick={removeBody} disabled={busy || !body}>
            {PROFILE_TEXT.deleteBody}
          </button>
          <button className="btn btn-danger btn-sm" onClick={removeAccount} disabled={busy}>
            {PROFILE_TEXT.deleteAccount}
          </button>
        </div>
      </div>
    </div>
  )
}
