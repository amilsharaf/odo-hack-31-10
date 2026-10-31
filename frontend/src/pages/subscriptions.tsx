import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  api, Badge, cap, Empty, Err, Field, fmtDate, isStaff, money, Obj, PageHead, Pager, Pipeline, qs, rowNav,
  SearchBox, Tabs, todayISO, useAuth, useDebounced, useFetch,
} from '../lib'

const STATUSES = ['draft', 'quotation', 'confirmed', 'active', 'paused', 'closed']
const PERIOD_WORD: Record<string, string> = { daily: 'day', weekly: 'week', monthly: 'month', yearly: 'year' }

export function Subscriptions() {
  const { user } = useAuth()
  const staff = isStaff(user)
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const q = useDebounced(search)
  const status = params.get('status') || ''
  const page = Number(params.get('page') || 1)
  const { data, error, loading } = useFetch<Obj>('/subscriptions' + qs({ status, q, page, page_size: 25 }))
  const setStatus = (s: string) => setParams(s ? { status: s } : {})

  const go = useNavigate()

  return (
    <>
      <PageHead title={staff ? 'Subscriptions' : 'My subscriptions'}>
        <Link to={staff ? '/subscriptions/new' : '/subscribe'}><button>{staff ? 'New subscription' : 'Start a subscription'}</button></Link>
      </PageHead>
      <Tabs value={status} onChange={setStatus} items={[{ value: '', label: 'All' }, ...STATUSES.map(s => ({ value: s, label: cap(s) }))]} />
      {staff && (
        <div className="toolbar">
          <SearchBox placeholder="Search number or customer" value={search} onChange={v => { setSearch(v); setParams(status ? { status } : {}) }} />
        </div>
      )}
      <Err msg={error} />
      <div className="tablewrap">
        <table>
          <thead>
            <tr><th>Number</th>{staff && <th>Customer</th>}<th>Plan</th><th>Status</th><th>Next invoice</th><th>Expires</th><th className="num">Recurring</th></tr>
          </thead>
          <tbody>
            {data?.items.map((s: Obj) => (
              <tr key={s.id} {...rowNav(go, `/subscriptions/${s.id}`)}>
                <td><Link className="id" to={`/subscriptions/${s.id}`}>{s.number}</Link></td>
                {staff && <td>{s.customer_name}</td>}
                <td>{s.plan_name}</td>
                <td><Badge value={s.status} /></td>
                <td>{s.status === 'active' ? fmtDate(s.next_billing_date) : <span className="muted">—</span>}</td>
                <td>{fmtDate(s.expiry_date)}</td>
                <td className="num strong">{money(s.recurring_amount)}<span className="muted"> /{PERIOD_WORD[s.plan_interval]}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.items.length === 0 && <Empty title={loading ? 'Loading…' : 'No subscriptions found'}>{loading ? '' : 'Try another status or search term.'}</Empty>}
      </div>
      {data && <Pager page={page} size={25} total={data.total} onPage={p => setParams({ ...(status ? { status } : {}), page: String(p) })} />}
    </>
  )
}

const ACTION_LABEL: Record<string, string> = {
  send_quote: 'Send quotation', confirm: 'Confirm', activate: 'Activate', pause: 'Pause',
  resume: 'Resume', renew: 'Renew', close: 'Close',
}

export function SubscriptionDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const staff = isStaff(user)
  const { data: s, error, reload } = useFetch<Obj>(`/subscriptions/${id}`)
  const invoices = useFetch<Obj>(`/invoices?subscription_id=${id}&page_size=50`)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState('lines')
  const go = useNavigate()

  const act = async (action: string) => {
    const cancelling = action === 'close'
    const msg = cancelling && ['draft', 'quotation', 'confirmed'].includes(s!.status)
      ? 'Cancel this subscription? It will be closed.'
      : cancelling ? 'Close this subscription now? Billing stops and this cannot be undone.' : ''
    if (msg && !window.confirm(msg)) return
    setBusy(true); setErr('')
    try { await api(`/subscriptions/${id}/transition`, { body: { action } }); reload(); invoices.reload() }
    catch (x: any) { setErr(x.message) } finally { setBusy(false) }
  }

  if (error) return <Err msg={error} />
  if (!s) return <p className="muted">Loading…</p>
  const editable = ['draft', 'quotation'].includes(s.status)
  const preStart = editable || s.status === 'confirmed'
  const actions: string[] = s.allowed_actions

  return (
    <>
      <PageHead title={s.number} crumbs={[{ label: staff ? 'Subscriptions' : 'My subscriptions', to: '/subscriptions' }, { label: s.number }]}>
        {editable && <Link to={`/subscriptions/${id}/edit`}><button className="secondary">Edit</button></Link>}
        {actions.filter(a => a !== 'close').map(a => (
          <button key={a} className={['confirm', 'activate', 'send_quote'].includes(a) ? '' : 'secondary'} disabled={busy} onClick={() => act(a)}>
            {ACTION_LABEL[a]}
          </button>
        ))}
        {actions.includes('close') && (
          <button className="danger" disabled={busy} onClick={() => act('close')}>{preStart ? 'Cancel' : 'Close'}</button>
        )}
      </PageHead>
      <Err msg={err} />
      <Pipeline steps={['draft', 'quotation', 'confirmed', 'active', 'closed']} current={s.status === 'paused' ? 'active' : s.status}
        tag={s.status === 'paused' ? <Badge value="paused" /> : undefined} />
      <div className="split">
        <div className="card flush">
          <div style={{ padding: '14px 20px 0' }}>
            <Tabs value={tab} onChange={setTab} items={[
              { value: 'lines', label: 'Lines' },
              { value: 'invoices', label: `Invoices${invoices.data ? ` (${invoices.data.total})` : ''}` },
            ]} />
          </div>
          {tab === 'lines' && (
            <>
              <div className="tablewrap">
                <table>
                  <thead><tr><th>Product</th><th className="num">Qty</th><th className="num">Unit price</th><th>Tax</th><th className="num">Amount</th></tr></thead>
                  <tbody>
                    {Number(s.plan_price) > 0 && (
                      <tr><td className="strong">{s.plan_name} plan fee</td><td className="num">1</td><td className="num">{money(s.plan_price)}</td><td className="muted">—</td><td className="num">{money(s.plan_price)}</td></tr>
                    )}
                    {s.lines.map((l: Obj) => (
                      <tr key={l.id}>
                        <td className="strong">{l.product_name}{l.variant && <span className="chip" style={{ marginLeft: 8 }}>{l.variant}</span>}</td>
                        <td className="num">{l.quantity}</td>
                        <td className="num">{money(l.unit_price)}</td>
                        <td>{l.tax_name ?? <span className="muted">—</span>}</td>
                        <td className="num">{money(l.net)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div style={{ padding: '4px 20px 20px' }}>
                <div className="totals">
                  <div><span>Subtotal</span><span>{money(s.subtotal)}</span></div>
                  <div><span>Tax</span><span>{money(s.tax_total)}</span></div>
                  <div className="sum"><span>Total per {PERIOD_WORD[s.plan_interval]}</span><span>{money(s.total)}</span></div>
                </div>
                <p className="muted small" style={{ textAlign: 'right', margin: '10px 0 0' }}>Before discounts. Any that apply are added to each invoice automatically.</p>
              </div>
            </>
          )}
          {tab === 'invoices' && (
            <>
              {invoices.data && invoices.data.items.length === 0 && <Empty title="No invoices yet">{staff ? 'They appear when the billing run reaches the next billing date.' : 'Nothing has been billed yet.'}</Empty>}
              {invoices.data && invoices.data.items.length > 0 && (
                <div className="tablewrap">
                  <table>
                    <thead><tr><th>Invoice</th><th>Period</th><th>Due</th><th>Status</th><th className="num">Total</th><th className="num">Balance</th></tr></thead>
                    <tbody>
                      {invoices.data.items.map((i: Obj) => (
                        <tr key={i.id} {...rowNav(go, `/invoices/${i.id}`)}>
                          <td><Link className="id" to={`/invoices/${i.id}`}>{i.number}</Link></td>
                          <td>{fmtDate(i.period_start)} – {fmtDate(i.period_end)}</td>
                          <td>{fmtDate(i.due_date)}</td>
                          <td><Badge value={i.display_status} /></td>
                          <td className="num">{money(i.total)}</td>
                          <td className="num strong">{money(i.balance)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>

        <aside className="card">
          <div className="facts">
            <div><div className="k">Customer</div><div className="v">{s.customer_name}</div></div>
            <div><div className="k">Plan</div><div className="v">{s.plan_name}</div><div className="muted small">Billed {s.plan_interval}</div></div>
            <div><div className="k">Recurring</div><div className="v num">{money(s.recurring_amount)} <span className="muted">/ {PERIOD_WORD[s.plan_interval]}</span></div></div>
            <div><div className="k">Term</div><div className="v">{fmtDate(s.start_date)} → {fmtDate(s.expiry_date)}</div></div>
            {s.status === 'active' && <div><div className="k">Next invoice</div><div className="v">{fmtDate(s.next_billing_date)}</div></div>}
            {s.status === 'quotation' && <div><div className="k">Quote valid until</div><div className="v">{fmtDate(s.quote_valid_until)}</div></div>}
            <div><div className="k">Payment terms</div><div className="v">{s.payment_term || 'Due on issue'}</div></div>
            {s.notes && <div><div className="k">Notes</div><div className="v" style={{ fontWeight: 400 }}>{s.notes}</div></div>}
          </div>
        </aside>
      </div>
    </>
  )
}

interface FormLine { product_id: string; variant_id: string; quantity: string; unit_price: string }
const blankLine = (): FormLine => ({ product_id: '', variant_id: '', quantity: '1', unit_price: '' })

/** One form for staff (any customer, negotiable prices, templates) and for customers (themselves, list prices). */
export function SubscriptionForm() {
  const { id } = useParams()
  const { user } = useAuth()
  const staff = isStaff(user)
  const nav = useNavigate()
  const products = useFetch<Obj[]>('/products')
  const plans = useFetch<Obj[]>('/plans')
  const terms = useFetch<Obj[]>('/payment-terms')
  const customers = useFetch<Obj>(staff ? '/customers?page_size=200' : null)
  const templates = useFetch<Obj[]>(staff ? '/templates' : null)
  const existing = useFetch<Obj>(id ? `/subscriptions/${id}` : null)

  const [f, setF] = useState({ customer_id: '', template_id: '', plan_id: '', payment_term_id: '', start_date: todayISO(), expiry_date: '', notes: '' })
  const [lines, setLines] = useState<FormLine[]>([blankLine()])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const s = existing.data
    if (!s) return
    setF({ customer_id: String(s.customer_id), template_id: '', plan_id: String(s.plan_id), payment_term_id: s.payment_term_id ? String(s.payment_term_id) : '',
      start_date: s.start_date, expiry_date: s.expiry_date, notes: s.notes || '' })
    setLines(s.lines.map((l: Obj) => ({ product_id: String(l.product_id), variant_id: l.variant_id ? String(l.variant_id) : '', quantity: String(l.quantity), unit_price: String(l.unit_price) })))
  }, [existing.data])

  const plan = plans.data?.find(p => String(p.id) === f.plan_id)
  const productOf = (pid: string) => products.data?.find(p => String(p.id) === pid)

  const pickTemplate = (tid: string) => {
    const t = templates.data?.find(x => String(x.id) === tid)
    setF(prev => ({ ...prev, template_id: tid, plan_id: t ? String(t.plan_id) : prev.plan_id }))
    if (t) setLines(t.lines.map((l: Obj) => ({ product_id: String(l.product_id), variant_id: l.variant_id ? String(l.variant_id) : '', quantity: String(l.quantity), unit_price: '' })))
  }

  const setLine = (i: number, patch: Partial<FormLine>) => setLines(ls => ls.map((l, j) => j === i ? { ...l, ...patch } : l))

  const unitFor = (l: FormLine) => {
    if (l.unit_price !== '') return Number(l.unit_price)
    const p = productOf(l.product_id)
    if (!p) return 0
    const v = p.variants.find((v: Obj) => String(v.id) === l.variant_id)
    return Number(p.sales_price) + Number(v?.extra_price ?? 0)
  }
  const estimate = useMemo(() => {
    let net = Number(plan?.price ?? 0), tax = net * Number(plan?.tax?.rate ?? 0) / 100
    for (const l of lines) {
      const n = unitFor(l) * Number(l.quantity || 0)
      net += n; tax += n * Number(productOf(l.product_id)?.tax?.rate ?? 0) / 100
    }
    return { net, tax }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lines, plan, products.data])

  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setBusy(true)
    const body: Obj = {
      plan_id: Number(f.plan_id), payment_term_id: staff && f.payment_term_id ? Number(f.payment_term_id) : null,
      start_date: f.start_date, expiry_date: f.expiry_date || null, notes: f.notes || null,
      lines: lines.map(l => ({
        product_id: Number(l.product_id), variant_id: l.variant_id ? Number(l.variant_id) : null,
        quantity: Number(l.quantity), unit_price: staff && l.unit_price !== '' ? l.unit_price : null,
      })),
    }
    try {
      let r: Obj
      if (id) r = await api(`/subscriptions/${id}`, { method: 'PATCH', body })
      else r = await api('/subscriptions', { body: { ...body, customer_id: staff ? Number(f.customer_id) : undefined, template_id: f.template_id ? Number(f.template_id) : null } })
      nav(`/subscriptions/${r.id}`)
    } catch (x: any) { setErr(x.message) } finally { setBusy(false) }
  }

  const today = todayISO()
  const offered = plans.data?.filter(p => (!p.valid_from || p.valid_from <= today) && (!p.valid_to || p.valid_to >= today)) ?? []

  return (
    <>
      <PageHead title={id ? 'Edit subscription' : staff ? 'New subscription' : 'Start a subscription'}
        sub={staff ? 'Start from a quotation template, or build the lines by hand.' : 'Pick a plan and what you need. You can review everything before it starts.'} />
      <form onSubmit={submit}>
        <Err msg={err} />
        <div className="card">
          <div className="formgrid">
            {staff && !id && (
              <Field label="Customer">
                <select value={f.customer_id} onChange={e => setF({ ...f, customer_id: e.target.value })} required>
                  <option value="">Choose…</option>
                  {customers.data?.items.map((c: Obj) => <option key={c.id} value={c.id}>{c.name}{c.company ? ` · ${c.company}` : ''}</option>)}
                </select>
              </Field>
            )}
            {staff && !id && (
              <Field label="Quotation template" hint="Fills the plan and lines; you can still change them.">
                <select value={f.template_id} onChange={e => pickTemplate(e.target.value)}>
                  <option value="">None — start blank</option>
                  {templates.data?.map(t => <option key={t.id} value={t.id}>{t.name} · valid {t.validity_days} days</option>)}
                </select>
              </Field>
            )}
            <Field label="Plan" hint={plan ? `${plan.interval} billing · minimum quantity ${plan.min_quantity}${Number(plan.price) > 0 ? ` · plan fee ${money(plan.price)}` : ''}` : undefined}>
              <select value={f.plan_id} onChange={e => setF({ ...f, plan_id: e.target.value })} required>
                <option value="">Choose…</option>
                {(staff ? plans.data ?? [] : offered).map(p => <option key={p.id} value={p.id}>{p.name} ({p.interval})</option>)}
              </select>
            </Field>
            {staff && (
              <Field label="Payment terms">
                <select value={f.payment_term_id} onChange={e => setF({ ...f, payment_term_id: e.target.value })}>
                  <option value="">Due on issue</option>
                  {terms.data?.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </Field>
            )}
            <Field label="Start date"><input type="date" value={f.start_date} onChange={e => setF({ ...f, start_date: e.target.value })} required /></Field>
            <Field label="Expiry date" hint="Leave empty for one year."><input type="date" value={f.expiry_date} min={f.start_date} onChange={e => setF({ ...f, expiry_date: e.target.value })} /></Field>
          </div>
          <Field label="Notes"><textarea value={f.notes} onChange={e => setF({ ...f, notes: e.target.value })} /></Field>
        </div>

        <div className="card">
          <h2>Lines</h2>
          <div className="tablewrap linestable" style={{ border: 0 }}>
            <table>
              <thead><tr><th>Product</th><th>Variant</th><th style={{ width: 90 }}>Qty</th>{staff && <th style={{ width: 130 }}>Unit price</th>}<th className="num">Line total</th><th /></tr></thead>
              <tbody>
                {lines.map((l, i) => {
                  const p = productOf(l.product_id)
                  return (
                    <tr key={i}>
                      <td>
                        <select value={l.product_id} onChange={e => setLine(i, { product_id: e.target.value, variant_id: '', unit_price: '' })} required aria-label="Product">
                          <option value="">Choose…</option>
                          {products.data?.map(pr => <option key={pr.id} value={pr.id}>{pr.name}</option>)}
                        </select>
                      </td>
                      <td>
                        {p?.variants.length ? (
                          <select value={l.variant_id} onChange={e => setLine(i, { variant_id: e.target.value, unit_price: '' })} required aria-label="Variant">
                            <option value="">Choose…</option>
                            {p.variants.map((v: Obj) => <option key={v.id} value={v.id}>{v.attribute}: {v.value}{Number(v.extra_price) ? ` (+${money(v.extra_price)})` : ''}</option>)}
                          </select>
                        ) : <span className="muted">—</span>}
                      </td>
                      <td><input type="number" min={Math.max(1, plan?.min_quantity ?? 1)} value={l.quantity} onChange={e => setLine(i, { quantity: e.target.value })} required aria-label="Quantity" /></td>
                      {staff && <td><input type="number" step="0.01" min="0" placeholder={unitFor({ ...l, unit_price: '' }).toFixed(2)} value={l.unit_price} onChange={e => setLine(i, { unit_price: e.target.value })} aria-label="Unit price" /></td>}
                      <td className="num">{money(unitFor(l) * Number(l.quantity || 0))}</td>
                      <td><button type="button" className="ghost" onClick={() => setLines(ls => ls.length > 1 ? ls.filter((_, j) => j !== i) : ls)} aria-label="Remove line">✕</button></td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr><td colSpan={staff ? 4 : 3} className="right">Estimated per period, before discounts (net + tax)</td><td className="num">{money(estimate.net + estimate.tax)}</td><td /></tr>
              </tfoot>
            </table>
          </div>
          <button type="button" className="secondary" style={{ marginTop: 10 }} onClick={() => setLines(ls => [...ls, blankLine()])}>Add line</button>
        </div>
        <div className="row gap" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
          <button type="button" className="ghost" onClick={() => nav(-1)}>Cancel</button>
          <button disabled={busy}>{busy ? 'Saving…' : id ? 'Save changes' : staff ? 'Create draft' : 'Request quotation'}</button>
        </div>
      </form>
    </>
  )
}
