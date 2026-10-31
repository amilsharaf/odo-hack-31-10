import { ReactNode, useEffect, useRef, useState } from 'react'
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { IconChevron, isStaff, RequireRole, useAuth } from './lib'
import { Forgot, Login, Register, Reset } from './pages/auth'
import Dashboard from './pages/dashboard'
import { SubscriptionDetail, SubscriptionForm, Subscriptions } from './pages/subscriptions'
import { BillingRun, InvoiceDetail, Invoices, Payments } from './pages/invoices'
import { Customers, Discounts, Plans, Products, Profile, Settings, Staff, Templates } from './pages/admin'

interface Item { to: string; label: string }

/** A dropdown that closes on outside click, Escape and navigation. */
function Menu({ label, items, align, trigger }: { label?: string; items?: Item[]; align?: 'right'; trigger?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const { pathname } = useLocation()
  useEffect(() => setOpen(false), [pathname])
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])
  const active = items?.some(i => pathname === i.to || pathname.startsWith(i.to + '/'))
  return (
    <div ref={box} className={`menu ${open ? 'open' : ''} ${active ? 'has-active' : ''}`}>
      <button aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        {trigger ?? <>{label}<IconChevron /></>}
      </button>
      {open && items && (
        <div className={`menu-pop ${align === 'right' ? 'right-edge' : ''}`} role="menu">
          {items.map(i => <NavLink key={i.to} to={i.to} role="menuitem" className={({ isActive }) => (isActive ? 'active' : '')}>{i.label}</NavLink>)}
        </div>
      )}
    </div>
  )
}

function UserMenu() {
  const { user, logout } = useAuth()
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open])
  const initials = (user?.name || '?').split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase()
  return (
    <div ref={box} className="userbtn menu">
      <button aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <span className="avatar">{initials}</span><IconChevron />
      </button>
      {open && (
        <div className="menu-pop right-edge" role="menu">
          <div className="pop-head"><div>{user?.name}</div><div className="muted small">{user?.email} · {user?.role}</div></div>
          {user?.role === 'customer' && <NavLink to="/profile" role="menuitem" onClick={() => setOpen(false)}>My details</NavLink>}
          <button className="item" role="menuitem" onClick={() => { logout(); nav('/login') }}>Sign out</button>
        </div>
      )}
    </div>
  )
}

function Shell({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const staff = isStaff(user)
  return (
    <>
      <header className="topbar">
        <Link to="/" className="logo"><b>B</b>Brightloop</Link>
        <nav className="nav" aria-label="Main">
          {staff ? (
            <>
              <NavLink to="/" end>Overview</NavLink>
              <Menu label="Sales" items={[{ to: '/subscriptions', label: 'Subscriptions' }, { to: '/customers', label: 'Customers' }]} />
              <Menu label="Billing" items={[{ to: '/invoices', label: 'Invoices' }, { to: '/payments', label: 'Payments' }, { to: '/billing', label: 'Billing run' }]} />
              <Menu label="Catalogue" items={[{ to: '/products', label: 'Products' }, { to: '/plans', label: 'Plans' }, { to: '/templates', label: 'Quotation templates' }, { to: '/discounts', label: 'Discounts' }]} />
              {user?.role === 'admin' && <Menu label="Admin" items={[{ to: '/settings', label: 'Taxes & payment terms' }, { to: '/staff', label: 'Staff' }]} />}
            </>
          ) : (
            <>
              <NavLink to="/" end>My subscriptions</NavLink>
              <NavLink to="/subscribe">Start a subscription</NavLink>
              <NavLink to="/invoices">My invoices</NavLink>
            </>
          )}
        </nav>
        <UserMenu />
      </header>
      <main className="main">{children}</main>
    </>
  )
}

export default function App() {
  const { user } = useAuth()
  const guard = (el: ReactNode, roles?: string[]) => <RequireRole roles={roles}><Shell>{el}</Shell></RequireRole>
  const S = ['admin', 'staff'], A = ['admin']
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/forgot-password" element={<Forgot />} />
      <Route path="/reset-password" element={<Reset />} />

      <Route path="/" element={guard(isStaff(user) ? <Dashboard /> : <Subscriptions />)} />
      <Route path="/subscriptions" element={guard(<Subscriptions />)} />
      <Route path="/subscriptions/new" element={guard(<SubscriptionForm />, S)} />
      <Route path="/subscribe" element={guard(<SubscriptionForm />, ['customer'])} />
      <Route path="/subscriptions/:id" element={guard(<SubscriptionDetail />)} />
      <Route path="/subscriptions/:id/edit" element={guard(<SubscriptionForm />)} />
      <Route path="/invoices" element={guard(<Invoices />)} />
      <Route path="/invoices/:id" element={guard(<InvoiceDetail />)} />
      <Route path="/payments" element={guard(<Payments />, S)} />
      <Route path="/billing" element={guard(<BillingRun />, S)} />
      <Route path="/customers" element={guard(<Customers />, S)} />
      <Route path="/products" element={guard(<Products />, S)} />
      <Route path="/plans" element={guard(<Plans />, S)} />
      <Route path="/templates" element={guard(<Templates />, S)} />
      <Route path="/discounts" element={guard(<Discounts />, S)} />
      <Route path="/settings" element={guard(<Settings />, A)} />
      <Route path="/staff" element={guard(<Staff />, A)} />
      <Route path="/profile" element={guard(<Profile />, ['customer'])} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
