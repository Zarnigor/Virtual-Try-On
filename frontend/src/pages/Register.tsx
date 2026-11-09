import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { register } from '../api/auth'
import { useAuthStore } from '../store/auth'

export default function Register() {
  const navigate = useNavigate()
  const { setTokens, setUser } = useAuthStore()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [adult, setAdult] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!adult) { setError('Yoshingizni tasdiqlashingiz kerak'); return }
    setError('')
    setLoading(true)
    try {
      const { data } = await register({ email, password, is_adult_confirmed: adult })
      setTokens(data.access, data.refresh)
      setUser(data.user)
      navigate('/')
    } catch (err: unknown) {
      const data = (err as { response?: { data?: Record<string, string[]> } })?.response?.data
      if (data) {
        const first = Object.values(data).flat()[0]
        setError(first || 'Roʻyxatdan oʻtishda xato')
      } else {
        setError('Roʻyxatdan oʻtishda xato')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        background: 'var(--bg)',
      }}
    >
      <div className="card" style={{ width: '100%', maxWidth: 420 }}>
        <h1 style={{ fontSize: 24, marginBottom: 8 }}>Roʻyxatdan oʻtish</h1>
        <p style={{ color: 'var(--muted)', fontSize: 14, marginBottom: 28 }}>
          Yangi TryOn Studio hisobi yarating
        </p>

        <form onSubmit={handleSubmit}>
          <div className="field">
            <label className="label" htmlFor="email">Email</label>
            <input
              id="email"
              className="input"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="sizning@email.com"
            />
          </div>
          <div className="field">
            <label className="label" htmlFor="password">Parol</label>
            <input
              id="password"
              className="input"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Kamida 8 ta belgi"
            />
          </div>

          <label
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 10,
              marginBottom: 20,
              cursor: 'pointer',
            }}
          >
            <input
              type="checkbox"
              checked={adult}
              onChange={(e) => setAdult(e.target.checked)}
              style={{ width: 18, height: 18, marginTop: 2, accentColor: 'var(--accent)', flexShrink: 0 }}
            />
            <span style={{ fontSize: 14, color: 'var(--text-soft)', lineHeight: 1.4 }}>
              Men 18 yoshdan kattaman va platformaning foydalanish shartlariga roziman
            </span>
          </label>

          {error && <p className="error-text" style={{ marginBottom: 12 }}>{error}</p>}

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%' }}
            disabled={loading}
          >
            {loading ? 'Kutilmoqda…' : 'Roʻyxatdan oʻtish'}
          </button>
        </form>

        <p style={{ marginTop: 20, textAlign: 'center', fontSize: 14, color: 'var(--muted)' }}>
          Hisob bormi? <Link to="/login">Kirish</Link>
        </p>
      </div>
    </div>
  )
}
