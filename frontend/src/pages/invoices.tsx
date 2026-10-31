import { FormEvent, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  api, Badge, cap, Empty, Err, Field, fmtDate, isStaff, Modal, money, Ok, Obj, PageHead, Pager, Pipeline, qs,
  rowNav, SearchBox, Tabs, todayISO, useAuth, useDebounced, useFetch,
} from '../lib'

const METHODS = ['card', 'bank_transfer', 'cash', 'upi', 'cheque']

export function Invoices() {
  const { user } = useAuth()
  const staff = isStaff(user)
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const q = useDebounced(search)
  const status = params.get('status') || ''
  const page = Number(params.get('page') || 1)
  const { data, error, loading } = useFetch<Obj>('/invoices' + qs({ status, q, page, page_size: 25 }))
  const set = (s: string) => setParams(s ? { status: s } : {})

  const go = useNavigate()
  const tabs = [
    { value: '', label: 'All' },
    ...(staff ? [{ value: 'draft', label: 'Draft' }] : []),
    { value: 'outstanding', label: 'Outstanding' },
    { value: 'overdue', label: 'Overdue' },
    { value: 'paid', label: 'Paid' },
    ...(staff ? [{ value: 'cancelled', label: 'Cancelled' }] : []),
  ]

  return (
    <>
      <PageHead title={staff ? 'Invoices' : 'My invoices'} />
      <Tabs value={status} onChange={set} items={tabs} />
      {staff && (
        <div className="toolbar">
          <SearchBox placeholder="Search number or customer" value={search} onChange={v => { setSearch(v); setParams(status ? { status } : {}) }} />
        </div>
      )}
      <Err msg={error} />
      <div className="tablewrap">
        <table>
          <thead><tr><th>Invoice</th>{staff && <th>Customer</th>}<th>Subscription</th><th>Status</th><th>Due</th><th className="num">Total</th><th className="num">Balance</th></tr></thead>
          <tbody>
            {data?.items.map((i: Obj) => (
              <tr key={i.id} {...rowNav(go, `/invoices/${i.id}`)}>
                <td><Link className="id" to={`/invoices/${i.id}`}>{i.number}</Link></td>
                {staff && <td>{i.customer_name}</td>}
                <td><Link to={`/subscriptions/${i.subscription_id}`}>{i.subscription_number}</Link></td>
                <td><Badge value={i.display_status} /></td>
                <td>{fmtDate(i.due_date)}{i.days_overdue > 0 && <span className="muted"> · {i.days_overdue}d late</span>}</td>
                <td className="num">{money(i.total)}</td>
                <td className="num strong">{Number(i.balance) ? money(i.balance) : <span className="muted">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.items.length === 0 && <Empty title={loading ? 'Loading…' : 'No invoices found'}>{loading ? '' : 'Try another status or search term.'}</Empty>}
      </div>
      {data && <Pager page={page} size={25} total={data.total} onPage={p => setParams({ ...(status ? { status } : {}), page: String(p) })} />}
    </>
  )
}

export function InvoiceDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const staff = isStaff(user)
  const { data: inv, error, reload } = useFetch<Obj>(`/invoices/${id}`)
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')
  const [paying, setPaying] = useState(false)
  const [busy, setBusy] = useState(false)

  const run = async (path: string, done?: string, confirmMsg?: string) => {
    if (confirmMsg && !window.confirm(confirmMsg)) return
    setBusy(true); setErr(''); setNote('')
    try { await api(`/invoices/${id}/${path}`, { method: 'POST' }); if (done) setNote(done); reload() }
    catch (x: any) { setErr(x.message) } finally { setBusy(false) }
  }

  if (error) return <Err msg={error} />
  if (!inv) return <p className="muted">Loading…</p>
  const open = inv.status === 'confirmed'

  const late = inv.days_overdue > 0
  return (
    <>
      <PageHead title={inv.number} crumbs={[{ label: staff ? 'Invoices' : 'My invoices', to: '/invoices' }, { label: inv.number }]}>
        {staff && inv.status === 'draft' && <button disabled={busy} onClick={() => run('confirm')}>Confirm</button>}
        {staff && open && <button disabled={busy} onClick={() => setPaying(true)}>Record payment</button>}
        {staff && (open || inv.status === 'paid') && <button className="secondary" disabled={busy} onClick={() => run('send', `Sent to ${inv.customer_email}`)}>{inv.sent_at ? 'Send again' : 'Send'}</button>}
        <button className="secondary" onClick={() => window.print()}>Print</button>
        {staff && (inv.status === 'draft' || open) && Number(inv.amount_paid) === 0 && (
          <button className="danger" disabled={busy} onClick={() => run('cancel', 'Invoice cancelled', 'Cancel this invoice? Any discount it used is returned.')}>Cancel invoice</button>
        )}
      </PageHead>
      <Err msg={err} /><Ok msg={note} />
      {inv.status === 'cancelled'
        ? <div className="alert no-print">This invoice was cancelled and no longer counts towards revenue.</div>
        : <Pipeline steps={['draft', 'confirmed', 'paid']} current={inv.status}
            tag={late ? <Badge value="overdue" /> : undefined} />}

      <div className="sheet">
        <div className="sheet-head">
          <div>
            <div className="doc">Invoice</div>
            <div className="no">{inv.number}</div>
          </div>
          <Badge value={inv.display_status} />
        </div>
        <div className="parties">
          <div>
            <div className="k">Billed to</div>
            <div className="v">{inv.customer_name}</div>
            <div>{inv.customer_email}</div>
            {inv.customer_address && <div className="muted">{inv.customer_address}</div>}
          </div>
          <div>
            <div className="k">Issued</div><div className="v">{fmtDate(inv.issue_date)}</div>
            <div className="k" style={{ marginTop: 8 }}>Due</div>
            <div className="v" style={late ? { color: 'var(--bad)' } : undefined}>{fmtDate(inv.due_date)}{late && ` · ${inv.days_overdue} days late`}</div>
          </div>
          <div>
            <div className="k">Service period</div><div className="v">{fmtDate(inv.period_start)} – {fmtDate(inv.period_end)}</div>
            <div className="k" style={{ marginTop: 8 }}>Subscription</div>
            <div className="v"><Link to={`/subscriptions/${inv.subscription_id}`}>{inv.subscription_number}</Link></div>
          </div>
        </div>

        <div className="tablewrap">
          <table>
            <thead><tr><th>Description</th><th className="num">Qty</th><th className="num">Unit price</th><th className="num">Discount</th><th className="num">Tax</th><th className="num">Amount</th></tr></thead>
            <tbody>
              {inv.lines.map((l: Obj) => (
                <tr key={l.id}>
                  <td className="strong">{l.description}</td>
                  <td className="num">{l.quantity}</td>
                  <td className="num">{money(l.unit_price)}</td>
                  <td className="num">{Number(l.discount_amount) ? `− ${money(l.discount_amount)}` : <span className="muted">—</span>}</td>
                  <td className="num">{Number(l.tax_rate) ? <>{money(l.tax_amount)} <span className="muted">({Number(l.tax_rate)}%)</span></> : <span className="muted">—</span>}</td>
                  <td className="num">{money(l.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="totals">
          <div><span>Subtotal</span><span>{money(inv.subtotal)}</span></div>
          {Number(inv.discount_total) > 0 && <div><span>Discounts</span><span>− {money(inv.discount_total)}</span></div>}
          <div><span>Tax</span><span>{money(inv.tax_total)}</span></div>
          <div className="sum"><span>Total</span><span>{money(inv.total)}</span></div>
          <div><span>Paid</span><span>{money(inv.amount_paid)}</span></div>
          <div className={`due ${late ? 'late' : Number(inv.balance) === 0 && inv.status !== 'cancelled' ? 'clear' : ''}`}><span>Balance due</span><span>{money(inv.balance)}</span></div>
        </div>
        {inv.sent_at && <p className="muted small no-print" style={{ marginBottom: 0 }}>Sent to the customer on {fmtDate(inv.sent_at)}.</p>}
      </div>

      <div className="card flush" style={{ marginTop: 16 }}>
        <div className="card-head"><h2>Payments</h2></div>
        {inv.payments.length === 0 ? <Empty>No payments recorded yet.</Empty> : (
          <div className="tablewrap" style={{ marginTop: 12 }}>
            <table>
              <thead><tr><th>Date</th><th>Method</th><th>Note</th><th className="num">Amount</th></tr></thead>
              <tbody>
                {inv.payments.map((p: Obj) => (
                  <tr key={p.id}><td>{fmtDate(p.paid_on)}</td><td>{cap(p.method)}</td><td>{p.note || <span className="muted">—</span>}</td><td className="num strong">{money(p.amount)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {paying && <PaymentModal inv={inv} onClose={() => setPaying(false)} onDone={() => { setPaying(false); reload() }} />}
    </>
  )
}

function PaymentModal({ inv, onClose, onDone }: { inv: Obj; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ method: 'bank_transfer', amount: String(inv.balance), paid_on: todayISO(), note: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr('')
    try { await api(`/invoices/${inv.id}/payments`, { body: { ...f, note: f.note || null } }); onDone() }
    catch (x: any) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <Modal title={`Record payment · ${inv.number}`} onClose={onClose}>
      <form onSubmit={submit}>
        <Err msg={err} />
        <p className="muted" style={{ marginTop: 0 }}>Outstanding balance: <strong>{money(inv.balance)}</strong>. A smaller amount is recorded as a part payment.</p>
        <div className="formgrid">
          <Field label="Method"><select value={f.method} onChange={e => setF({ ...f, method: e.target.value })}>{METHODS.map(m => <option key={m} value={m}>{cap(m)}</option>)}</select></Field>
          <Field label="Amount"><input type="number" step="0.01" min="0.01" max={inv.balance} value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} required autoFocus /></Field>
          <Field label="Date received"><input type="date" max={todayISO()} value={f.paid_on} onChange={e => setF({ ...f, paid_on: e.target.value })} required /></Field>
        </div>
        <Field label="Note"><input value={f.note} onChange={e => setF({ ...f, note: e.target.value })} placeholder="Reference, cheque number…" /></Field>
        <div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>Cancel</button><button disabled={busy}>Record payment</button></div>
      </form>
    </Modal>
  )
}

export function Payments() {
  const [params, setParams] = useSearchParams()
  const method = params.get('method') || ''
  const page = Number(params.get('page') || 1)
  const { data, error } = useFetch<Obj>('/payments' + qs({ method, page, page_size: 25 }))
  const go = useNavigate()
  return (
    <>
      <PageHead title="Payments" />
      <Tabs value={method} onChange={m => setParams(m ? { method: m } : {})}
        items={[{ value: '', label: 'All' }, ...METHODS.map(m => ({ value: m, label: cap(m) }))]} />
      <Err msg={error} />
      <div className="tablewrap">
        <table>
          <thead><tr><th>Date</th><th>Invoice</th><th>Customer</th><th>Method</th><th>Note</th><th className="num">Amount</th></tr></thead>
          <tbody>
            {data?.items.map((p: Obj) => (
              <tr key={p.id} {...rowNav(go, `/invoices/${p.invoice_id}`)}>
                <td>{fmtDate(p.paid_on)}</td>
                <td><Link className="id" to={`/invoices/${p.invoice_id}`}>{p.invoice_number}</Link></td>
                <td>{p.customer_name}</td><td>{cap(p.method)}</td><td>{p.note || <span className="muted">—</span>}</td><td className="num strong">{money(p.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.items.length === 0 && <Empty title="No payments found">Nothing has been recorded for this filter.</Empty>}
      </div>
      {data && <Pager page={page} size={25} total={data.total} onPage={p => setParams({ ...(method ? { method } : {}), page: String(p) })} />}
    </>
  )
}

export function BillingRun() {
  const due = useFetch<Obj>('/billing/due')
  const [asOf, setAsOf] = useState(todayISO())
  const [autoConfirm, setAutoConfirm] = useState(false)
  const [result, setResult] = useState<Obj | null>(null)
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const run = async () => {
    setBusy(true); setErr(''); setNote('')
    try { setResult(await api('/billing/run', { body: { as_of: asOf, auto_confirm: autoConfirm } })); due.reload() }
    catch (x: any) { setErr(x.message) } finally { setBusy(false) }
  }
  const confirmDrafts = async () => {
    setBusy(true); setErr('')
    try { const r = await api('/invoices/confirm-drafts', { method: 'POST' }); setNote(`${r.confirmed} draft invoices confirmed`); due.reload() }
    catch (x: any) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <>
      <PageHead title="Billing run" sub="Creates an invoice for every subscription period that has come due. Safe to run again: nothing is billed twice." />
      <Err msg={err} /><Ok msg={note} />
      <div className="metrics" style={{ maxWidth: 520 }}>
        <div className="metric"><div className="label">Subscriptions due now</div><div className="value">{due.data?.subscriptions_due ?? '—'}</div></div>
        <div className="metric"><div className="label">Draft invoices waiting</div><div className="value">{due.data?.draft_invoices ?? '—'}</div></div>
      </div>
      <div className="grid2">
        <div className="card">
          <h2>Run billing</h2>
          <Field label="Bill everything due up to" hint="Defaults to today. Choose a later date to see next period's invoices early."><input type="date" value={asOf} onChange={e => setAsOf(e.target.value)} /></Field>
          <label className="check"><input type="checkbox" checked={autoConfirm} onChange={e => setAutoConfirm(e.target.checked)} />Confirm invoices as they are created</label>
          <button disabled={busy} onClick={run}>{busy ? 'Working…' : 'Run billing'}</button>
        </div>
        <div className="card">
          <h2>Review and confirm</h2>
          <p className="muted" style={{ marginTop: 0 }}>Invoices start as drafts so they can be checked. Confirm them all at once when you are happy, or open them one by one from the <Link to="/invoices?status=draft">draft list</Link>.</p>
          <button className="secondary" disabled={busy || !due.data?.draft_invoices} onClick={confirmDrafts}>Confirm all drafts</button>
        </div>
      </div>
      {result && (
        <div className="card">
          <h2>Result as of {fmtDate(result.as_of)}</h2>
          <dl className="dl">
            <dt>Invoices created</dt><dd className="num">{result.invoices_created} across {result.subscriptions_billed} subscriptions</dd>
            <dt>Already billed (skipped)</dt><dd className="num">{result.already_billed}</dd>
            <dt>Subscriptions activated</dt><dd className="num">{result.activated}</dd>
            <dt>Closed on expiry</dt><dd className="num">{result.closed}</dd>
            <dt>Lapsed quotations closed</dt><dd className="num">{result.quotes_expired}</dd>
          </dl>
          {result.errors.length > 0 && <div className="alert" style={{ marginTop: 12 }}>{result.errors.map((e: string) => <div key={e}>{e}</div>)}</div>}
        </div>
      )}
    </>
  )
}
