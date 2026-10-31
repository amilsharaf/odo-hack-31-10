import { FormEvent, ReactNode, useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { api, Err, Field, IconCheck, Ok, useAuth } from '../lib'

function AuthFrame({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <div className="auth">
      <div className="auth-pane">
        <div className="logo"><b>B</b>Brightloop</div>
        <div className="body">
          <h1>{title}</h1>
          {sub && <p className="muted" style={{ margin: '4px 0 0' }}>{sub}</p>}
          <div style={{ marginTop: 22 }}>{children}</div>
        </div>
      </div>
      <aside className="auth-side">
        <h2>Every subscription, invoice and payment in one place.</h2>
        <ul>
          {[
            ['Billing that never double-charges', 'Each period is invoiced exactly once, even if the run is repeated.'],
            ['Quotation to cash', 'Quote, confirm, activate, invoice and record payment without leaving the system.'],
            ['Clear for customers', 'Customers see their own subscriptions and invoices, and nothing else.'],
          ].map(([h, p]) => (
            <li key={h}><span className="tick"><IconCheck /></span><div><b>{h}</b><span>{p}</span></div></li>
          ))}
        </ul>
      </aside>
    </div>
  )
}

const PASSWORD_HINT = 'More than 8 characters, with an uppercase letter, a lowercase letter and a special character.'

/** Mirrors the server rules so people see what is missing before submitting. The server stays the authority. */
function passwordProblems(pw: string) {
  const out: string[] = []
  if (pw.length <= 8) out.push('more than 8 characters')
  if (!/[A-Z]/.test(pw)) out.push('an uppercase letter')
  if (!/[a-z]/.test(pw)) out.push('a lowercase letter')
  if (!/[^A-Za-z0-9]/.test(pw)) out.push('a special character')
  return out
}

export function Login() {
  const { user, login } = useAuth()
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  if (user) return <Navigate to="/" replace />
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr('')
    try {
      const r = await api('/auth/login', { body: { email, password } })
      login(r.access_token, r.user); nav('/')
    } catch (x: any) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <AuthFrame title="Sign in" sub="Subscriptions, invoices and payments in one place.">
      <form onSubmit={submit}>
        <Err msg={err} />
        <Field label="Email"><input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoFocus autoComplete="username" /></Field>
        <Field label="Password"><input type="password" value={password} onChange={e => setPassword(e.target.value)} required autoComplete="current-password" /></Field>
        <button style={{ width: '100%' }} disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <div className="row" style={{ justifyContent: 'space-between', marginTop: 14 }}>
          <Link to="/forgot-password">Forgot password?</Link>
          <Link to="/register">Create an account</Link>
        </div>
      </form>
    </AuthFrame>
  )
}

export function Register() {
  const { login } = useAuth()
  const nav = useNavigate()
  const [f, setF] = useState({ name: '', email: '', password: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const problems = passwordProblems(f.password)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr('')
    try {
      const r = await api('/auth/register', { body: f })
      login(r.access_token, r.user); nav('/')
    } catch (x: any) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <AuthFrame title="Create your account" sub="Manage your subscriptions and invoices yourself.">
      <form onSubmit={submit}>
        <Err msg={err} />
        <Field label="Full name"><input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} required autoFocus /></Field>
        <Field label="Email" hint="One account per email address."><input type="email" value={f.email} onChange={e => setF({ ...f, email: e.target.value })} required autoComplete="username" /></Field>
        <Field label="Password" hint={f.password && problems.length ? `Still needs: ${problems.join(', ')}.` : PASSWORD_HINT}>
          <input type="password" value={f.password} onChange={e => setF({ ...f, password: e.target.value })} required autoComplete="new-password" />
        </Field>
        <button style={{ width: '100%' }} disabled={busy || problems.length > 0}>{busy ? 'Creating…' : 'Create account'}</button>
        <p style={{ marginTop: 14 }}>Already registered? <Link to="/login">Sign in</Link></p>
      </form>
    </AuthFrame>
  )
}

export function Forgot() {
  const [email, setEmail] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr('')
    try { const r = await api('/auth/forgot-password', { body: { email } }); setMsg(r.message) } catch (x: any) { setErr(x.message) }
  }
  return (
    <AuthFrame title="Reset your password" sub="We will email a link to your registered address.">
      <form onSubmit={submit}>
        <Err msg={err} /><Ok msg={msg} />
        <Field label="Email"><input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoFocus /></Field>
        <button style={{ width: '100%' }}>Send reset link</button>
        <p style={{ marginTop: 14 }}><Link to="/login">Back to sign in</Link></p>
        {import.meta.env.DEV && (
          <p className="muted" style={{ fontSize: 12.5 }}>
            Demo build: outgoing mail is captured, not sent. Open <a href="/api/dev/mails" target="_blank" rel="noreferrer">the dev mailbox</a> to follow the link.
          </p>
        )}
      </form>
    </AuthFrame>
  )
}

export function Reset() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const token = params.get('token') || ''
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [done, setDone] = useState(false)
  const problems = passwordProblems(password)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr('')
    try {
      await api('/auth/reset-password', { body: { token, password } })
      setDone(true); setTimeout(() => nav('/login'), 1500)
    } catch (x: any) { setErr(x.message) }
  }
  return (
    <AuthFrame title="Choose a new password">
      {!token ? <Err msg="This link is missing its token. Request a new one." /> : (
        <form onSubmit={submit}>
          <Err msg={err} /><Ok msg={done ? 'Password updated. Taking you to sign in…' : ''} />
          <Field label="New password" hint={password && problems.length ? `Still needs: ${problems.join(', ')}.` : PASSWORD_HINT}>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} required autoFocus autoComplete="new-password" />
          </Field>
          <button style={{ width: '100%' }} disabled={problems.length > 0 || done}>Update password</button>
        </form>
      )}
    </AuthFrame>
  )
}
