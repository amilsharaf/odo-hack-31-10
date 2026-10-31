import { FormEvent, ReactNode, useEffect, useState } from 'react'
import {
  api, Badge, cap, dateWindow, Empty, Err, Field, Modal, money, Ok, Obj, PageHead, Pager, qs, useAuth,
  useDebounced, useFetch,
} from '../lib'

/** Modal form wrapper: handles busy/error state and closes on success. */
function FormModal({ title, onClose, onSave, children, wide }: {
  title: string; onClose: () => void; onSave: () => Promise<any>; children: ReactNode; wide?: boolean
}) {
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr('')
    try { await onSave() } catch (x: any) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <Modal title={title} onClose={onClose} wide={wide}>
      <form onSubmit={submit}>
        <Err msg={err} />
        {children}
        <div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>Cancel</button><button disabled={busy}>{busy ? 'Saving…' : 'Save'}</button></div>
      </form>
    </Modal>
  )
}

const nul = (v: string) => (v === '' ? null : v)
const Check = ({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) => (
  <label className="check"><input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />{label}</label>
)

// ---------------- customers ----------------
export function Customers() {
  const [search, setSearch] = useState('')
  const q = useDebounced(search)
  const [page, setPage] = useState(1)
  const { data, error, reload } = useFetch<Obj>('/customers' + qs({ q, page, page_size: 25 }))
  const [edit, setEdit] = useState<Obj | null>(null)
  return (
    <>
      <PageHead title="Customers" sub="People and companies you bill."><button onClick={() => setEdit({})}>Add customer</button></PageHead>
      <div className="toolbar"><input type="search" placeholder="Search name, company or email" value={search} onChange={e => { setSearch(e.target.value); setPage(1) }} aria-label="Search" /></div>
      <Err msg={error} />
      <div className="tablewrap">
        <table>
          <thead><tr><th>Name</th><th>Company</th><th>Email</th><th>Phone</th><th>Portal</th><th /></tr></thead>
          <tbody>
            {data?.items.map((c: Obj) => (
              <tr key={c.id}>
                <td>{c.name}</td><td>{c.company || '—'}</td><td>{c.email}</td><td>{c.phone || '—'}</td>
                <td>{c.user_id ? <span className="chip">has login</span> : <span className="muted">none</span>}</td>
                <td className="right"><button className="ghost" onClick={() => setEdit(c)}>Edit</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.items.length === 0 && <Empty>No customers yet.</Empty>}
      </div>
      {data && <Pager page={page} size={25} total={data.total} onPage={setPage} />}
      {edit && <CustomerForm c={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </>
  )
}

function CustomerForm({ c, onClose, onSaved }: { c: Obj; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ name: c.name || '', email: c.email || '', company: c.company || '', phone: c.phone || '', address: c.address || '' })
  return (
    <FormModal title={c.id ? 'Edit customer' : 'New customer'} onClose={onClose} onSave={async () => {
      const body = { ...f, company: nul(f.company), phone: nul(f.phone), address: nul(f.address) }
      await api(c.id ? `/customers/${c.id}` : '/customers', { method: c.id ? 'PUT' : 'POST', body }); onSaved()
    }}>
      <div className="formgrid">
        <Field label="Name"><input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} required autoFocus /></Field>
        <Field label="Email"><input type="email" value={f.email} onChange={e => setF({ ...f, email: e.target.value })} required /></Field>
        <Field label="Company"><input value={f.company} onChange={e => setF({ ...f, company: e.target.value })} /></Field>
        <Field label="Phone"><input value={f.phone} onChange={e => setF({ ...f, phone: e.target.value })} /></Field>
      </div>
      <Field label="Billing address"><textarea value={f.address} onChange={e => setF({ ...f, address: e.target.value })} /></Field>
    </FormModal>
  )
}

export function Profile() {
  const { data, error } = useFetch<Obj>('/customers/me')
  const [f, setF] = useState({ name: '', company: '', phone: '', address: '' })
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  useEffect(() => { if (data) setF({ name: data.name, company: data.company || '', phone: data.phone || '', address: data.address || '' }) }, [data])
  const save = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setMsg('')
    try { await api('/customers/me', { method: 'PUT', body: { ...f, email: data!.email, company: nul(f.company), phone: nul(f.phone), address: nul(f.address) } }); setMsg('Saved') }
    catch (x: any) { setErr(x.message) }
  }
  return (
    <>
      <PageHead title="My details" sub="Shown on your invoices." />
      <Err msg={error || err} /><Ok msg={msg} />
      {data && (
        <form className="card" style={{ maxWidth: 560 }} onSubmit={save}>
          <Field label="Email" hint="This is your sign-in address."><input value={data.email} disabled /></Field>
          <Field label="Name"><input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} required /></Field>
          <div className="formgrid">
            <Field label="Company"><input value={f.company} onChange={e => setF({ ...f, company: e.target.value })} /></Field>
            <Field label="Phone"><input value={f.phone} onChange={e => setF({ ...f, phone: e.target.value })} /></Field>
          </div>
          <Field label="Billing address"><textarea value={f.address} onChange={e => setF({ ...f, address: e.target.value })} /></Field>
          <button>Save</button>
        </form>
      )}
    </>
  )
}

// ---------------- products ----------------
export function Products() {
  const { user } = useAuth()
  const admin = user?.role === 'admin'
  const { data, error, reload } = useFetch<Obj[]>('/products?include_inactive=true')
  const taxes = useFetch<Obj[]>('/taxes')
  const [edit, setEdit] = useState<Obj | null>(null)
  return (
    <>
      <PageHead title="Products" sub="What you sell, with variants that change the price.">{admin && <button onClick={() => setEdit({})}>Add product</button>}</PageHead>
      <Err msg={error} />
      <div className="tablewrap">
        <table>
          <thead><tr><th>Name</th><th>Type</th><th className="num">Sales price</th><th className="num">Cost</th><th>Tax</th><th>Variants</th><th /></tr></thead>
          <tbody>
            {data?.map(p => (
              <tr key={p.id} style={p.active ? undefined : { opacity: .55 }}>
                <td>{p.name}{!p.active && <span className="chip" style={{ marginLeft: 8 }}>inactive</span>}</td>
                <td>{cap(p.type)}</td><td className="num">{money(p.sales_price)}</td><td className="num">{money(p.cost_price)}</td>
                <td>{p.tax?.name || '—'}</td>
                <td><div className="chips">{p.variants.map((v: Obj) => <span className="chip" key={v.id}>{v.value}{Number(v.extra_price) ? ` +${Number(v.extra_price)}` : ''}</span>)}</div></td>
                <td className="right">{admin && <button className="ghost" onClick={() => setEdit(p)}>Edit</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.length === 0 && <Empty>No products yet.</Empty>}
      </div>
      {edit && <ProductForm p={edit} taxes={taxes.data ?? []} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </>
  )
}

function ProductForm({ p, taxes, onClose, onSaved }: { p: Obj; taxes: Obj[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ name: p.name || '', type: p.type || 'service', sales_price: p.sales_price ?? '', cost_price: p.cost_price ?? '0', tax_id: p.tax_id ? String(p.tax_id) : '', notes: p.notes || '', active: p.active ?? true })
  const [variants, setVariants] = useState<Obj[]>(p.variants?.map((v: Obj) => ({ attribute: v.attribute, value: v.value, extra_price: v.extra_price })) ?? [])
  return (
    <FormModal wide title={p.id ? 'Edit product' : 'New product'} onClose={onClose} onSave={async () => {
      const body = { ...f, tax_id: f.tax_id ? Number(f.tax_id) : null, notes: nul(f.notes), variants: variants.filter(v => v.attribute && v.value) }
      await api(p.id ? `/products/${p.id}` : '/products', { method: p.id ? 'PUT' : 'POST', body }); onSaved()
    }}>
      <div className="formgrid">
        <Field label="Name"><input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} required autoFocus /></Field>
        <Field label="Type">
          <select value={f.type} onChange={e => setF({ ...f, type: e.target.value })}>
            {['service', 'software', 'addon', 'physical'].map(t => <option key={t} value={t}>{cap(t)}</option>)}
          </select>
        </Field>
        <Field label="Sales price"><input type="number" step="0.01" min="0" value={f.sales_price} onChange={e => setF({ ...f, sales_price: e.target.value })} required /></Field>
        <Field label="Cost price"><input type="number" step="0.01" min="0" value={f.cost_price} onChange={e => setF({ ...f, cost_price: e.target.value })} /></Field>
        <Field label="Tax"><select value={f.tax_id} onChange={e => setF({ ...f, tax_id: e.target.value })}><option value="">No tax</option>{taxes.filter(t => t.active || String(t.id) === f.tax_id).map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field>
      </div>
      <Field label="Notes"><textarea value={f.notes} onChange={e => setF({ ...f, notes: e.target.value })} /></Field>
      <h3 style={{ margin: '4px 0 8px' }}>Variants</h3>
      <p className="muted" style={{ marginTop: 0 }}>For example attribute “Brand”, value “Odoo”, extra price 560 sells that variant at the base price plus 560. When variants exist, one must be chosen on every line.</p>
      {variants.map((v, i) => (
        <div className="row gap" key={i} style={{ marginBottom: 8 }}>
          <input placeholder="Attribute (Brand)" value={v.attribute} onChange={e => setVariants(vs => vs.map((x, j) => j === i ? { ...x, attribute: e.target.value } : x))} aria-label="Attribute" />
          <input placeholder="Value (Odoo)" value={v.value} onChange={e => setVariants(vs => vs.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} aria-label="Value" />
          <input type="number" step="0.01" placeholder="Extra price" value={v.extra_price} onChange={e => setVariants(vs => vs.map((x, j) => j === i ? { ...x, extra_price: e.target.value } : x))} aria-label="Extra price" />
          <button type="button" className="ghost" onClick={() => setVariants(vs => vs.filter((_, j) => j !== i))} aria-label="Remove variant">✕</button>
        </div>
      ))}
      <button type="button" className="secondary" onClick={() => setVariants(vs => [...vs, { attribute: vs[vs.length - 1]?.attribute || '', value: '', extra_price: '0' }])}>Add variant</button>
      <div style={{ marginTop: 14 }}><Check label="Available to sell" checked={f.active} onChange={v => setF({ ...f, active: v })} /></div>
    </FormModal>
  )
}

// ---------------- plans ----------------
export function Plans() {
  const { user } = useAuth()
  const admin = user?.role === 'admin'
  const { data, error, reload } = useFetch<Obj[]>('/plans?include_inactive=true')
  const taxes = useFetch<Obj[]>('/taxes')
  const [edit, setEdit] = useState<Obj | null>(null)
  const flag = (on: boolean, label: string) => on ? <span className="chip">{label}</span> : null
  const none = (p: Obj) => !(p.auto_close || p.closable || p.pausable || p.renewable)
  return (
    <>
      <PageHead title="Plans" sub="How often it bills, who can change it, and when it is offered.">{admin && <button onClick={() => setEdit({})}>Add plan</button>}</PageHead>
      <Err msg={error} />
      <div className="tablewrap">
        <table>
          <thead><tr><th>Plan</th><th>Billing</th><th className="num">Plan fee</th><th className="num">Min qty</th><th>Available</th><th>Allows</th><th /></tr></thead>
          <tbody>
            {data?.map(p => (
              <tr key={p.id} style={p.active ? undefined : { opacity: .55 }}>
                <td>{p.name}{!p.active && <span className="chip" style={{ marginLeft: 8 }}>inactive</span>}</td>
                <td>{cap(p.interval)}</td><td className="num">{money(p.price)}</td><td className="num">{p.min_quantity}</td>
                <td style={{ whiteSpace: 'nowrap' }}>{dateWindow(p.valid_from, p.valid_to)}</td>
                <td><div className="chips">{flag(p.auto_close, 'auto-close')}{flag(p.closable, 'close early')}{flag(p.pausable, 'pause')}{flag(p.renewable, 'renew')}{none(p) && <span className="muted">—</span>}</div></td>
                <td className="right">{admin && <button className="ghost" onClick={() => setEdit(p)}>Edit</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.length === 0 && <Empty>No plans yet.</Empty>}
      </div>
      {edit && <PlanForm p={edit} taxes={taxes.data ?? []} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </>
  )
}

function PlanForm({ p, taxes, onClose, onSaved }: { p: Obj; taxes: Obj[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({
    name: p.name || '', price: p.price ?? '0', interval: p.interval || 'monthly', min_quantity: p.min_quantity ?? 1,
    valid_from: p.valid_from || '', valid_to: p.valid_to || '', tax_id: p.tax_id ? String(p.tax_id) : '',
    auto_close: p.auto_close ?? false, closable: p.closable ?? true, pausable: p.pausable ?? false, renewable: p.renewable ?? true, active: p.active ?? true,
  })
  return (
    <FormModal wide title={p.id ? 'Edit plan' : 'New plan'} onClose={onClose} onSave={async () => {
      const body = { ...f, min_quantity: Number(f.min_quantity), valid_from: nul(f.valid_from), valid_to: nul(f.valid_to), tax_id: f.tax_id ? Number(f.tax_id) : null }
      await api(p.id ? `/plans/${p.id}` : '/plans', { method: p.id ? 'PUT' : 'POST', body }); onSaved()
    }}>
      <div className="formgrid">
        <Field label="Name"><input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} required autoFocus /></Field>
        <Field label="Billing period"><select value={f.interval} onChange={e => setF({ ...f, interval: e.target.value })}>{['daily', 'weekly', 'monthly', 'yearly'].map(i => <option key={i} value={i}>{cap(i)}</option>)}</select></Field>
        <Field label="Plan fee per period" hint="Charged on every invoice on top of the product lines. Use 0 for none."><input type="number" step="0.01" min="0" value={f.price} onChange={e => setF({ ...f, price: e.target.value })} required /></Field>
        <Field label="Plan fee tax"><select value={f.tax_id} onChange={e => setF({ ...f, tax_id: e.target.value })}><option value="">No tax</option>{taxes.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field>
        <Field label="Minimum quantity" hint="Per product line."><input type="number" min="1" value={f.min_quantity} onChange={e => setF({ ...f, min_quantity: e.target.value })} required /></Field>
        <span />
        <Field label="Available from"><input type="date" value={f.valid_from} onChange={e => setF({ ...f, valid_from: e.target.value })} /></Field>
        <Field label="Available until"><input type="date" value={f.valid_to} min={f.valid_from} onChange={e => setF({ ...f, valid_to: e.target.value })} /></Field>
      </div>
      <h3 style={{ margin: '4px 0 8px' }}>What can happen to a subscription on this plan</h3>
      <Check label="Closes on its own when the term ends" checked={f.auto_close} onChange={v => setF({ ...f, auto_close: v })} />
      <Check label="Can be closed early" checked={f.closable} onChange={v => setF({ ...f, closable: v })} />
      <Check label="Can be paused" checked={f.pausable} onChange={v => setF({ ...f, pausable: v })} />
      <Check label="Can be renewed" checked={f.renewable} onChange={v => setF({ ...f, renewable: v })} />
      <div style={{ marginTop: 8 }}><Check label="Offered to new subscriptions" checked={f.active} onChange={v => setF({ ...f, active: v })} /></div>
    </FormModal>
  )
}

// ---------------- templates ----------------
export function Templates() {
  const { user } = useAuth()
  const admin = user?.role === 'admin'
  const { data, error, reload } = useFetch<Obj[]>('/templates')
  const plans = useFetch<Obj[]>('/plans')
  const products = useFetch<Obj[]>('/products')
  const [edit, setEdit] = useState<Obj | null>(null)
  return (
    <>
      <PageHead title="Quotation templates" sub="Ready-made offers: plan, product lines and how long the quote stays valid.">{admin && <button onClick={() => setEdit({})}>Add template</button>}</PageHead>
      <Err msg={error} />
      <div className="tablewrap">
        <table>
          <thead><tr><th>Template</th><th>Plan</th><th>Lines</th><th className="num">Valid for</th><th /></tr></thead>
          <tbody>
            {data?.map(t => (
              <tr key={t.id}>
                <td>{t.name}</td><td>{t.plan.name}</td>
                <td><div className="chips">{t.lines.map((l: Obj) => <span className="chip" key={l.id}>{l.quantity} × {products.data?.find(p => p.id === l.product_id)?.name ?? `#${l.product_id}`}</span>)}</div></td>
                <td className="num">{t.validity_days} days</td>
                <td className="right">{admin && <button className="ghost" onClick={() => setEdit(t)}>Edit</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.length === 0 && <Empty>No templates yet.</Empty>}
      </div>
      {edit && <TemplateForm t={edit} plans={plans.data ?? []} products={products.data ?? []} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </>
  )
}

function TemplateForm({ t, plans, products, onClose, onSaved }: { t: Obj; plans: Obj[]; products: Obj[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ name: t.name || '', validity_days: t.validity_days ?? 30, plan_id: t.plan_id ? String(t.plan_id) : '', notes: t.notes || '' })
  const [lines, setLines] = useState<Obj[]>(t.lines?.map((l: Obj) => ({ product_id: String(l.product_id), variant_id: l.variant_id ? String(l.variant_id) : '', quantity: l.quantity })) ?? [{ product_id: '', variant_id: '', quantity: 1 }])
  const set = (i: number, patch: Obj) => setLines(ls => ls.map((l, j) => j === i ? { ...l, ...patch } : l))
  return (
    <FormModal wide title={t.id ? 'Edit template' : 'New template'} onClose={onClose} onSave={async () => {
      const body = { ...f, validity_days: Number(f.validity_days), plan_id: Number(f.plan_id), notes: nul(f.notes),
        lines: lines.filter(l => l.product_id).map(l => ({ product_id: Number(l.product_id), variant_id: l.variant_id ? Number(l.variant_id) : null, quantity: Number(l.quantity) })) }
      await api(t.id ? `/templates/${t.id}` : '/templates', { method: t.id ? 'PUT' : 'POST', body }); onSaved()
    }}>
      <div className="formgrid">
        <Field label="Name"><input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} required autoFocus /></Field>
        <Field label="Quote valid for (days)"><input type="number" min="1" value={f.validity_days} onChange={e => setF({ ...f, validity_days: e.target.value })} required /></Field>
        <Field label="Plan"><select value={f.plan_id} onChange={e => setF({ ...f, plan_id: e.target.value })} required><option value="">Choose…</option>{plans.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
      </div>
      <h3 style={{ margin: '4px 0 8px' }}>Lines</h3>
      {lines.map((l, i) => {
        const p = products.find(x => String(x.id) === l.product_id)
        return (
          <div className="row gap" key={i} style={{ marginBottom: 8 }}>
            <select value={l.product_id} onChange={e => set(i, { product_id: e.target.value, variant_id: '' })} aria-label="Product"><option value="">Product…</option>{products.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
            <select value={l.variant_id} onChange={e => set(i, { variant_id: e.target.value })} disabled={!p?.variants.length} aria-label="Variant" required={!!p?.variants.length}>
              <option value="">{p?.variants.length ? 'Variant…' : 'No variants'}</option>{p?.variants.map((v: Obj) => <option key={v.id} value={v.id}>{v.attribute}: {v.value}</option>)}
            </select>
            <input type="number" min="1" style={{ width: 90 }} value={l.quantity} onChange={e => set(i, { quantity: e.target.value })} aria-label="Quantity" />
            <button type="button" className="ghost" onClick={() => setLines(ls => ls.filter((_, j) => j !== i))} aria-label="Remove line">✕</button>
          </div>
        )
      })}
      <button type="button" className="secondary" onClick={() => setLines(ls => [...ls, { product_id: '', variant_id: '', quantity: 1 }])}>Add line</button>
      <Field label="Notes"><textarea value={f.notes} onChange={e => setF({ ...f, notes: e.target.value })} /></Field>
    </FormModal>
  )
}

// ---------------- discounts ----------------
export function Discounts() {
  const { user } = useAuth()
  const admin = user?.role === 'admin'
  const { data, error, reload } = useFetch<Obj[]>('/discounts')
  const products = useFetch<Obj[]>('/products')
  const [edit, setEdit] = useState<Obj | null>(null)
  const today = new Date().toISOString().slice(0, 10)
  const state = (d: Obj) => !d.active ? 'inactive' : d.end_date && d.end_date < today ? 'expired' : d.start_date && d.start_date > today ? 'scheduled'
    : d.usage_limit !== null && d.used_count >= d.usage_limit ? 'used up' : 'live'
  return (
    <>
      <PageHead title="Discounts" sub="Applied to invoices automatically while they are valid and have uses left.">{admin && <button onClick={() => setEdit({})}>Add discount</button>}</PageHead>
      {!admin && <p className="muted">Only the admin can create or change discount rules.</p>}
      <Err msg={error} />
      <div className="tablewrap">
        <table>
          <thead><tr><th>Name</th><th>Value</th><th>Applies to</th><th>Conditions</th><th>Valid</th><th className="num">Used</th><th>State</th><th /></tr></thead>
          <tbody>
            {data?.map(d => (
              <tr key={d.id}>
                <td>{d.name}</td>
                <td className="num">{d.kind === 'percent' ? `${Number(d.value)}%` : money(d.value)}</td>
                <td>{d.scope === 'subscription' ? 'Whole subscription' : d.product_ids.map((id: number) => products.data?.find(p => p.id === id)?.name ?? `#${id}`).join(', ')}</td>
                <td>{[Number(d.min_purchase) > 0 && `min ${money(d.min_purchase)}`, d.min_quantity > 0 && `min qty ${d.min_quantity}`].filter(Boolean).join(' · ') || '—'}</td>
                <td style={{ whiteSpace: 'nowrap' }}>{dateWindow(d.start_date, d.end_date)}</td>
                <td className="num">{d.used_count}{d.usage_limit !== null ? ` / ${d.usage_limit}` : ''}</td>
                <td><Badge value={state(d) === 'live' ? 'active' : state(d) === 'scheduled' ? 'quotation' : 'closed'} /> <span className="muted">{state(d)}</span></td>
                <td className="right">{admin && <button className="ghost" onClick={() => setEdit(d)}>Edit</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.length === 0 && <Empty>No discount rules.</Empty>}
      </div>
      {edit && <DiscountForm d={edit} products={products.data ?? []} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </>
  )
}

function DiscountForm({ d, products, onClose, onSaved }: { d: Obj; products: Obj[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({
    name: d.name || '', kind: d.kind || 'percent', value: d.value ?? '', scope: d.scope || 'product', min_purchase: d.min_purchase ?? '0',
    min_quantity: d.min_quantity ?? 0, start_date: d.start_date || '', end_date: d.end_date || '', usage_limit: d.usage_limit ?? '', active: d.active ?? true,
  })
  const [ids, setIds] = useState<number[]>(d.product_ids ?? [])
  const toggle = (id: number) => setIds(x => x.includes(id) ? x.filter(i => i !== id) : [...x, id])
  return (
    <FormModal wide title={d.id ? 'Edit discount' : 'New discount'} onClose={onClose} onSave={async () => {
      const body = { ...f, min_quantity: Number(f.min_quantity), start_date: nul(f.start_date), end_date: nul(f.end_date),
        usage_limit: f.usage_limit === '' ? null : Number(f.usage_limit), product_ids: f.scope === 'product' ? ids : [] }
      await api(d.id ? `/discounts/${d.id}` : '/discounts', { method: d.id ? 'PUT' : 'POST', body }); onSaved()
    }}>
      <div className="formgrid">
        <Field label="Name"><input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} required autoFocus /></Field>
        <Field label="Applies to"><select value={f.scope} onChange={e => setF({ ...f, scope: e.target.value })}><option value="product">Specific products</option><option value="subscription">Whole subscription</option></select></Field>
        <Field label="Type"><select value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}><option value="percent">Percentage</option><option value="fixed">Fixed amount</option></select></Field>
        <Field label={f.kind === 'percent' ? 'Percent off' : 'Amount off'} hint={f.scope === 'product' ? 'Fixed amounts come off each matching line once.' : 'Fixed amounts come off the invoice once.'}>
          <input type="number" step="0.01" min="0.01" max={f.kind === 'percent' ? 100 : undefined} value={f.value} onChange={e => setF({ ...f, value: e.target.value })} required />
        </Field>
        <Field label="Minimum purchase" hint={f.scope === 'product' ? 'Line value before discount.' : 'Invoice value before discount.'}><input type="number" step="0.01" min="0" value={f.min_purchase} onChange={e => setF({ ...f, min_purchase: e.target.value })} /></Field>
        <Field label="Minimum quantity"><input type="number" min="0" value={f.min_quantity} onChange={e => setF({ ...f, min_quantity: e.target.value })} /></Field>
        <Field label="Starts"><input type="date" value={f.start_date} onChange={e => setF({ ...f, start_date: e.target.value })} /></Field>
        <Field label="Ends"><input type="date" value={f.end_date} min={f.start_date} onChange={e => setF({ ...f, end_date: e.target.value })} /></Field>
        <Field label="Usage limit" hint={d.id ? `Used ${d.used_count} so far. Empty means unlimited.` : 'Empty means unlimited.'}><input type="number" min="1" value={f.usage_limit} onChange={e => setF({ ...f, usage_limit: e.target.value })} /></Field>
      </div>
      {f.scope === 'product' && (
        <Field label="Products">
          <div className="chips">
            {products.map(p => <label className="check" key={p.id} style={{ margin: 0 }}><input type="checkbox" checked={ids.includes(p.id)} onChange={() => toggle(p.id)} />{p.name}</label>)}
          </div>
        </Field>
      )}
      <Check label="Active" checked={f.active} onChange={v => setF({ ...f, active: v })} />
    </FormModal>
  )
}

// ---------------- taxes & payment terms ----------------
export function Settings() {
  const taxes = useFetch<Obj[]>('/taxes')
  const terms = useFetch<Obj[]>('/payment-terms')
  const [tax, setTax] = useState<Obj | null>(null)
  const [term, setTerm] = useState(false)
  const [err, setErr] = useState('')
  const delTerm = async (id: number) => {
    setErr('')
    try { await api(`/payment-terms/${id}`, { method: 'DELETE' }); terms.reload() } catch (x: any) { setErr(x.message) }
  }
  return (
    <>
      <PageHead title="Taxes & payment terms" sub="Tax rules are applied to invoice lines automatically." />
      <Err msg={err} />
      <div className="grid2">
        <div className="card">
          <div className="row" style={{ justifyContent: 'space-between' }}><h2>Taxes</h2><button className="secondary" onClick={() => setTax({})}>Add tax</button></div>
          <table>
            <thead><tr><th>Name</th><th className="num">Rate</th><th>State</th><th /></tr></thead>
            <tbody>{taxes.data?.map(t => (
              <tr key={t.id}><td>{t.name}</td><td className="num">{Number(t.rate)}%</td><td>{t.active ? 'In use' : 'Off'}</td><td className="right"><button className="ghost" onClick={() => setTax(t)}>Edit</button></td></tr>
            ))}</tbody>
          </table>
        </div>
        <div className="card">
          <div className="row" style={{ justifyContent: 'space-between' }}><h2>Payment terms</h2><button className="secondary" onClick={() => setTerm(true)}>Add term</button></div>
          <table>
            <thead><tr><th>Name</th><th className="num">Due after</th><th /></tr></thead>
            <tbody>{terms.data?.map(t => (
              <tr key={t.id}><td>{t.name}</td><td className="num">{t.days} days</td><td className="right"><button className="ghost" onClick={() => delTerm(t.id)}>Delete</button></td></tr>
            ))}</tbody>
          </table>
        </div>
      </div>
      {tax && <TaxForm t={tax} onClose={() => setTax(null)} onSaved={() => { setTax(null); taxes.reload() }} />}
      {term && <TermForm onClose={() => setTerm(false)} onSaved={() => { setTerm(false); terms.reload() }} />}
    </>
  )
}

function TaxForm({ t, onClose, onSaved }: { t: Obj; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ name: t.name || '', rate: t.rate ?? '', active: t.active ?? true })
  return (
    <FormModal title={t.id ? 'Edit tax' : 'New tax'} onClose={onClose} onSave={async () => { await api(t.id ? `/taxes/${t.id}` : '/taxes', { method: t.id ? 'PUT' : 'POST', body: f }); onSaved() }}>
      <Field label="Name"><input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} required autoFocus /></Field>
      <Field label="Rate (%)" hint="Changing a rate applies to invoices created from now on."><input type="number" step="0.01" min="0" max="100" value={f.rate} onChange={e => setF({ ...f, rate: e.target.value })} required /></Field>
      <Check label="In use" checked={f.active} onChange={v => setF({ ...f, active: v })} />
    </FormModal>
  )
}

function TermForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ name: '', days: '30' })
  return (
    <FormModal title="New payment term" onClose={onClose} onSave={async () => { await api('/payment-terms', { body: { name: f.name, days: Number(f.days) } }); onSaved() }}>
      <Field label="Name"><input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} required autoFocus placeholder="Net 45" /></Field>
      <Field label="Due this many days after issue"><input type="number" min="0" value={f.days} onChange={e => setF({ ...f, days: e.target.value })} required /></Field>
    </FormModal>
  )
}

// ---------------- staff ----------------
export function Staff() {
  const { user } = useAuth()
  const { data, error, reload } = useFetch<Obj[]>('/users')
  const [adding, setAdding] = useState(false)
  const [err, setErr] = useState('')
  const toggle = async (u: Obj) => {
    setErr('')
    try { await api(`/users/${u.id}/active?active=${!u.is_active}`, { method: 'PATCH' }); reload() } catch (x: any) { setErr(x.message) }
  }
  return (
    <>
      <PageHead title="Staff" sub="Staff handle customers and billing day to day, without access to the catalogue or settings."><button onClick={() => setAdding(true)}>Add staff member</button></PageHead>
      <Err msg={error || err} />
      <div className="tablewrap">
        <table>
          <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>State</th><th /></tr></thead>
          <tbody>{data?.map(u => (
            <tr key={u.id}>
              <td>{u.name}</td><td>{u.email}</td><td>{cap(u.role)}</td><td>{u.is_active ? 'Active' : 'Disabled'}</td>
              <td className="right">{u.id !== user?.id && <button className="ghost" onClick={() => toggle(u)}>{u.is_active ? 'Disable' : 'Enable'}</button>}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {adding && <StaffForm onClose={() => setAdding(false)} onSaved={() => { setAdding(false); reload() }} />}
    </>
  )
}

function StaffForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ name: '', email: '', password: '' })
  return (
    <FormModal title="New staff member" onClose={onClose} onSave={async () => { await api('/users/staff', { body: f }); onSaved() }}>
      <Field label="Name"><input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} required autoFocus /></Field>
      <Field label="Email"><input type="email" value={f.email} onChange={e => setF({ ...f, email: e.target.value })} required /></Field>
      <Field label="Temporary password" hint="More than 8 characters, with an uppercase letter, a lowercase letter and a special character. They can change it with “Forgot password”."><input type="password" value={f.password} onChange={e => setF({ ...f, password: e.target.value })} required autoComplete="new-password" /></Field>
    </FormModal>
  )
}
