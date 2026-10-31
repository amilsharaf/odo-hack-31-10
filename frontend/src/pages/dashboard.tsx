import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Badge, cap, Empty, Err, fmtDate, money, Obj, PageHead, qs, rowNav, todayISO, useFetch } from '../lib'

const monthStart = () => todayISO().slice(0, 8) + '01'
const STATUS_ORDER = ['active', 'paused', 'confirmed', 'quotation', 'draft', 'closed']
const STATUS_COLOR: Record<string, string> = {
  active: '#12b76a', paused: '#f79009', confirmed: '#2e90fa', quotation: '#98a2b3', draft: '#d0d5dd', closed: '#e4e7ec',
}
const n = (v: number) => v.toLocaleString('en-IN')

function Metric({ label, value, sub, bad }: { label: string; value: string; sub?: string; bad?: boolean }) {
  return (
    <div className={`metric ${bad ? 'bad' : ''}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

/** Compact axis label: 1.2L, 3.4Cr, 45k. */
function short(v: number) {
  if (v >= 1e7) return (v / 1e7).toFixed(1).replace(/\.0$/, '') + 'Cr'
  if (v >= 1e5) return (v / 1e5).toFixed(1).replace(/\.0$/, '') + 'L'
  if (v >= 1e3) return (v / 1e3).toFixed(0) + 'k'
  return String(Math.round(v))
}

function RevenueChart({ rows }: { rows: Obj[] }) {
  const max = Math.max(1, ...rows.flatMap(r => [Number(r.billed), Number(r.collected)]))
  return (
    <>
      <div className="legend">
        <span><i style={{ background: '#c7d4f7' }} />Invoiced</span>
        <span><i style={{ background: 'var(--accent)' }} />Collected</span>
      </div>
      <div className="chart" role="img" aria-label="Invoiced and collected revenue by month">
        <div className="axis"><span>{short(max)}</span><span>{short(max * 2 / 3)}</span><span>{short(max / 3)}</span><span>0</span></div>
        <div className="plot">
          {rows.map(r => (
            <div className="col" key={r.month}>
              <div className="bar b1" style={{ height: `${(Number(r.billed) / max) * 100}%` }} title={`Invoiced ${money(r.billed)}`} />
              <div className="bar b2" style={{ height: `${(Number(r.collected) / max) * 100}%` }} title={`Collected ${money(r.collected)}`} />
              <small>{new Date(r.month + '-01T00:00:00').toLocaleDateString('en-GB', { month: 'short' })}</small>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

export default function Dashboard() {
  const go = useNavigate()
  const [from, setFrom] = useState(monthStart())
  const [to, setTo] = useState(todayISO())
  const sum = useFetch<Obj>('/reports/summary' + qs({ date_from: from, date_to: to }))
  const series = useFetch<Obj[]>('/reports/revenue-series?months=6')
  const overdue = useFetch<Obj>('/invoices?status=overdue&page_size=8')
  const s = sum.data
  const byStatus: Obj = s?.subscriptions_by_status ?? {}
  const total = Object.values(byStatus).reduce((a: number, b: any) => a + Number(b), 0) || 1

  return (
    <>
      <PageHead title="Overview">
        <input type="date" aria-label="From" value={from} max={to} onChange={e => setFrom(e.target.value)} style={{ width: 150 }} />
        <span className="muted">to</span>
        <input type="date" aria-label="To" value={to} min={from} onChange={e => setTo(e.target.value)} style={{ width: 150 }} />
      </PageHead>
      <Err msg={sum.error} />
      {s && (
        <div className="metrics">
          <Metric label="Active subscriptions" value={n(s.active_subscriptions)} sub={`${n(byStatus.paused ?? 0)} paused · ${n(byStatus.quotation ?? 0)} quotes`} />
          <Metric label="Monthly recurring revenue" value={money(s.mrr)} sub={`${money(s.arr)} a year`} />
          <Metric label="Collected in range" value={money(s.collected_in_range)} sub={`of ${money(s.billed_in_range)} invoiced`} />
          <Metric label="Outstanding" value={money(s.outstanding_amount)} sub={`${n(s.outstanding_count)} open invoices`} />
          <Metric bad={s.overdue_count > 0} label="Overdue" value={money(s.overdue_amount)} sub={`${n(s.overdue_count)} past due`} />
        </div>
      )}

      <div className="split" style={{ gridTemplateColumns: 'minmax(0, 1.7fr) minmax(280px, 1fr)' }}>
        <div className="card">
          <div className="card-head"><h2>Revenue, last six months</h2></div>
          {series.data ? <RevenueChart rows={series.data} /> : <p className="muted">Loading…</p>}
        </div>
        <div className="card">
          <div className="card-head"><h2>Subscriptions</h2><span className="muted num">{n(s ? total : 0)} total</span></div>
          {s && (
            <>
              <div className="statusbar-stack" aria-hidden="true">
                {STATUS_ORDER.filter(k => byStatus[k]).map(k => <div key={k} style={{ flex: byStatus[k], background: STATUS_COLOR[k] }} />)}
              </div>
              <div className="listrows">
                {STATUS_ORDER.map(k => (
                  <Link key={k} className="r" to={`/subscriptions?status=${k}`}>
                    <span><i className="sdot" style={{ background: STATUS_COLOR[k] }} />{cap(k)}</span>
                    <span className="num">{n(byStatus[k] ?? 0)}</span>
                  </Link>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="card flush" style={{ marginTop: 16 }}>
        <div className="card-head"><h2>Overdue invoices to chase</h2><Link to="/invoices?status=overdue">View all</Link></div>
        {overdue.data && overdue.data.items.length === 0 && <Empty title="Nothing overdue">Every issued invoice is within its due date.</Empty>}
        {overdue.data && overdue.data.items.length > 0 && (
          <div className="tablewrap" style={{ marginTop: 12 }}>
            <table>
              <thead><tr><th>Invoice</th><th>Customer</th><th>Due</th><th>Status</th><th className="num">Balance</th></tr></thead>
              <tbody>
                {overdue.data.items.map((i: Obj) => (
                  <tr key={i.id} {...rowNav(go, `/invoices/${i.id}`)}>
                    <td><Link className="id" to={`/invoices/${i.id}`}>{i.number}</Link></td>
                    <td>{i.customer_name}</td>
                    <td>{fmtDate(i.due_date)} <span className="muted">· {i.days_overdue}d late</span></td>
                    <td><Badge value="overdue" /></td>
                    <td className="num strong">{money(i.balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
