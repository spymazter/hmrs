import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { BarChart3, Fingerprint, ShieldCheck, Wallet } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { Notice } from '../components/ui'

const DEMO = [
  { label: 'Admin', username: 'admin', password: 'admin123' },
  { label: 'HR', username: 'hr', password: 'hr123' },
  { label: 'Payroll', username: 'payroll', password: 'payroll123' },
  { label: 'Manager', username: 'manager', password: 'manager123' },
  { label: 'Employee', username: 'employee', password: 'emp123' },
]

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ username: '', password: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const loggedIn = await login(form.username, form.password)
      navigate((loggedIn.roles || []).length === 1 && loggedIn.roles[0].name === 'Employee' ? '/portal' : '/', { replace: true })
    } catch (err) {
      setError(err.response?.data?.detail || 'Unable to sign in')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-left">
        <div className="login-brand"><span className="logo-mark"><Fingerprint size={23} /></span> HRMS</div>
        <div className="login-hero">
          <h1>Attendance, people and payroll — in one place.</h1>
          <p>Connect your eSSL / ZKTeco biometric device, track punch in and punch out automatically, and run payroll from a single, secure workspace.</p>
          <div className="login-features">
            <span><Fingerprint size={13} /> Biometric sync</span>
            <span><BarChart3 size={13} /> Daily / weekly / monthly reports</span>
            <span><Wallet size={13} /> Payroll & salary slips</span>
            <span><ShieldCheck size={13} /> Role groups</span>
          </div>
        </div>
        <small>© {new Date().getFullYear()} HRMS. Built for modern workplaces.</small>
      </div>
      <div className="login-right">
        <div className="login-card">
          <h2>Welcome back</h2>
          <p>Sign in to your HRMS account to continue.</p>
          <Notice type="error">{error}</Notice>
          <form onSubmit={submit}>
            <div className="field">
              <label>Username</label>
              <input autoFocus value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="Enter your username" required />
            </div>
            <div className="field" style={{ marginTop: 16 }}>
              <label>Password</label>
              <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="Enter your password" required />
            </div>
            <button className="btn btn-primary" style={{ width: '100%', marginTop: 22, padding: 11 }} disabled={busy}>
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
          <div className="demo-box">
            <h4>Quick access · demo accounts</h4>
            <div className="demo-row">
              {DEMO.map((d) => (
                <button key={d.username} onClick={() => setForm({ username: d.username, password: d.password })}>{d.label}</button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
