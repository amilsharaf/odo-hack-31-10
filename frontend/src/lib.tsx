import { createContext, MouseEvent as ReactMouseEvent, ReactNode, useCallback, useContext, useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'

// ---------- api ----------
export type Obj = Record<string, any>
const TOKEN_KEY = 'bl_token'
export const getToken = () => localStorage.getItem(TOKEN_KEY)

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

/** FastAPI sends either a string or a list of validation problems; flatten to readable text. */
function detailText(d: any): string {
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map(e => {
    const field = (e.loc || []).filter((x: any) => x !== 'body').join('.')
    return field ? `${field}: ${e.msg}` : e.msg
  }).join('; ')
  return 'Something went wrong'
}

export async function api<T = any>(path: string, opts: { method?: string; body?: any } = {}): Promise<T> {
  const token = getToken()
  const res = await fetch('/api' + path, {
    method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'),
    headers: { ...(opts.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
               ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  })
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    if (res.status === 401 && token) { localStorage.removeItem(TOKEN_KEY); window.location.href = '/login' }
    throw new ApiError(res.status, detailText(data.detail))
  }
  return data
}

export function useFetch<T = any>(path: string | null, deps: any[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (path === null) return
    let live = true
    setLoading(true)
    api<T>(path).then(d => { if (live) { setData(d); setError('') } })
      .catch(e => { if (live) setError(e.message) })
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ...deps])
  return { data, error, loading, reload: () => setTick(t => t + 1) }
}

// ---------- auth ----------
export interface User { id: number; email: string; name: string; role: 'admin' | 'staff' | 'customer'; customer_id: number | null }
const AuthCtx = createContext<{ user: User | null; ready: boolean; login: (t: string, u: User) => void; logout: () => void }>(null as any)
export const useAuth = () => useContext(AuthCtx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  useEffect(() => {
    if (!getToken()) { setReady(true); return }
    api<User>('/auth/me').then(setUser).catch(() => localStorage.removeItem(TOKEN_KEY)).finally(() => setReady(true))
  }, [])
  const login = useCallback((t: string, u: User) => { localStorage.setItem(TOKEN_KEY, t); setUser(u) }, [])
  const logout = useCallback(() => { localStorage.removeItem(TOKEN_KEY); setUser(null) }, [])
  return <AuthCtx.Provider value={{ user, ready, login, logout }}>{children}</AuthCtx.Provider>
}

export function RequireRole({ roles, children }: { roles?: string[]; children: ReactNode }) {
  const { user, ready } = useAuth()
  if (!ready) return <p className="muted pad">Loading…</p>
  if (!user) return <Navigate to="/login" replace />
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />
  return <>{children}</>
}

export const isStaff = (u: User | null) => u?.role === 'admin' || u?.role === 'staff'

// ---------- formatting ----------
const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 })
export const money = (v: any) => inr.format(Number(v ?? 0))
export const fmtDate = (d?: string | null) => d ? new Date(d + (d.length === 10 ? 'T00:00:00' : '')).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'
/** "Always", "From 1 Jan 2026", "Until 31 Dec 2026" or "1 Jan 2026 – 31 Dec 2026". */
export const dateWindow = (from?: string | null, to?: string | null) =>
  from && to ? `${fmtDate(from)} – ${fmtDate(to)}` : from ? `From ${fmtDate(from)}` : to ? `Until ${fmtDate(to)}` : 'Always'
export const cap =(s: string) => s.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())
export const todayISO = () => new Date().toISOString().slice(0, 10)

// ---------- small UI kit ----------
export function Badge({ value }: { value: string }) {
  return <span className={`badge b-${value}`}><i />{cap(value)}</span>
}

const icon = (d: string) => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
)
export const IconSearch = () => icon('M7 12.5a5.5 5.5 0 1 0 0-11 5.5 5.5 0 0 0 0 11ZM14.5 14.5l-3.6-3.6')
export const IconChevron = () => icon('M4 6l4 4 4-4')
export const IconCheck = () => icon('M3 8.5l3.2 3.2L13 4.8')

export interface Crumb { label: string; to?: string }

/** Breadcrumb + title + actions, the "control panel" row Odoo puts above every view. */
export function PageHead({ title, sub, crumbs, children }: { title: string; sub?: string; crumbs?: Crumb[]; children?: ReactNode }) {
  return (
    <>
      {crumbs && (
        <nav className="crumbs" aria-label="Breadcrumb">
          {crumbs.map((c, i) => (
            <span key={i} className="row gap" style={{ gap: 6 }}>
              {i > 0 && <span className="sep">/</span>}
              {c.to ? <Link to={c.to}>{c.label}</Link> : <span>{c.label}</span>}
            </span>
          ))}
        </nav>
      )}
      <div className="pagehead">
        <div><h1>{title}</h1>{sub && <p>{sub}</p>}</div>
        {children && <div className="actions">{children}</div>}
      </div>
    </>
  )
}

/** Underlined filter tabs, as on Stripe's invoice list. */
export function Tabs({ items, value, onChange }: { items: { value: string; label: string }[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="tabs" role="tablist">
      {items.map(t => (
        <button key={t.value} role="tab" aria-selected={value === t.value} className={value === t.value ? 'on' : ''} onClick={() => onChange(t.value)}>{t.label}</button>
      ))}
    </div>
  )
}

export function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <div className="search">
      <IconSearch />
      <input type="search" placeholder={placeholder} value={value} onChange={e => onChange(e.target.value)} aria-label={placeholder} />
    </div>
  )
}

/** Odoo-style status pipeline: where the record is, what came before, what is still ahead. */
export function Pipeline({ steps, current, tag }: { steps: string[]; current: string; tag?: ReactNode }) {
  const at = steps.indexOf(current)
  return (
    <div className="pipeline" aria-label="Status">
      {steps.map((s, i) => (
        <div key={s} className={`step ${i < at ? 'done' : i === at ? 'now' : ''}`} aria-current={i === at ? 'step' : undefined}>{cap(s)}</div>
      ))}
      {tag && <div className="side-tag">{tag}</div>}
    </div>
  )
}

/** Whole-row navigation for list tables; real links inside the row keep working. */
export function rowNav(go: (to: string) => void, to: string) {
  return {
    className: 'click',
    onClick: (e: ReactMouseEvent) => { if (!(e.target as HTMLElement).closest('a,button,input,select')) go(to) },
  }
}

export function Err({ msg }: { msg: string }) { return msg ? <div className="alert" role="alert">{msg}</div> : null }
export function Ok({ msg }: { msg: string }) { return msg ? <div className="notice" role="status">{msg}</div> : null }

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small className="muted">{hint}</small>}
    </label>
  )
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div className="scrim" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head"><h2>{title}</h2><button className="ghost" onClick={onClose} aria-label="Close">✕</button></div>
        {children}
      </div>
    </div>
  )
}

export function Pager({ page, size, total, onPage }: { page: number; size: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size))
  const from = total === 0 ? 0 : (page - 1) * size + 1
  const to = Math.min(page * size, total)
  const n = (v: number) => v.toLocaleString('en-IN')
  return (
    <div className="pager">
      <span className="num">{n(from)}–{n(to)} of {n(total)}</span>
      <div className="btns">
        <button className="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <span className="num">Page {n(page)} of {n(pages)}</span>
        <button className="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </div>
  )
}

export function Empty({ children, title }: { children: ReactNode; title?: string }) {
  return <div className="empty">{title && <strong>{title}</strong>}{children}</div>
}

export function RowLink({ to, children }: { to: string; children: ReactNode }) { return <Link to={to}>{children}</Link> }

/** Debounce a fast-changing value (search boxes) so we do not call the API per keystroke. */
export function useDebounced<T>(value: T, ms = 300) {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

export function qs(params: Obj) {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v !== '' && v !== undefined && v !== null) p.set(k, String(v)) })
  const s = p.toString()
  return s ? '?' + s : ''
}
