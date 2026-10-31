# Brightloop Subscription Management

One system for the whole life of a subscription business: products and plans, quotations, subscriptions,
recurring invoices, discounts, payments and a finance overview. Built for the Odoo Hackathon
"Subscription Management System" problem.

**Stack:** FastAPI + SQLAlchemy 2 (PostgreSQL) · React + TypeScript (Vite) · JWT auth with bcrypt.

## Run it

You need Python 3.11+ and Node 18+.

```bash
# 1. database (skip if you use SQLite, see below)
docker compose up -d db

# 2. backend
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows. On macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python seed.py                    # wipes and loads demo data
DEV_MAILBOX=true uvicorn app.main:app --port 8000

# 3. frontend (new terminal)
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

No Docker or Postgres? Use SQLite for a quick look: set `DATABASE_URL=sqlite:///./dev.db` for both
`python seed.py` and `uvicorn`. Everything works the same; Postgres is the intended database.

`DEV_MAILBOX=true` exposes captured outgoing mail at `/api/dev/mails` so the password-reset link can be
followed during a demo. It is off by default because it publishes every email body, reset links included.

### Demo logins (from `seed.py`)

| Role | Email | Password |
|---|---|---|
| Admin | admin@brightloop.example.com | Admin@12345 |
| Staff | staff@brightloop.example.com | Staff@12345 |
| Customer | customer@acme.example.com | Customer@12345 |

`python seed.py --bulk 5000 --keep` adds 5,000 subscriptions with billed and paid history for the
performance check below.

### Tests

```bash
cd backend && pytest        # 40 tests: pricing engine, auth, roles, lifecycle, billing, discounts, payments
cd frontend && npm run build
```

## How each part of the brief is handled

| Scene | Where it lives |
|---|---|
| Sign up, unique email, password rule, reset link | `routers/auth.py`, `security.py`. Password must be **more than 8** characters with upper, lower and special. Email is stored lowercase and unique. Reset tokens are random, only their hash is stored, single use, 60 min expiry. The "forgot" form answers identically for unknown emails. |
| Admin / staff / customer | `deps.py`. Only the admin can create staff, products, plans, taxes, templates and discounts. Staff run customers, subscriptions, invoices, payments, reports. Customers are scoped to their own records at query level; someone else's record returns 404, not 403. |
| Product, variants, plan | `models.py`, `routers/catalog.py`. A variant (Brand = Odoo, +560) adds to the base price. Plans carry interval, minimum quantity, availability dates and four admin flags: auto-close, close early, pause, renew. |
| Quote to subscription | Quotation templates prefill plan and lines and set a quote validity. Lifecycle Draft → Quotation → Confirmed → Active → Closed (plus Paused), enforced in `services/subscriptions.py`. A lapsed quote can no longer be confirmed and is closed by the next billing run. |
| Billing day | `services/billing.py`. One run creates every due invoice with customer, lines, discounts, tax and totals filled in. Invoices go Draft → Confirmed → Paid, and can be cancelled, sent (mail) or printed. |
| Discounts | Admin-only rules: fixed or percent, min purchase, min quantity, date window, usage limit, scoped to products or the whole subscription. Applied automatically at billing; a use is claimed atomically so the limit holds under concurrency. Cancelling an invoice returns the use. |
| Payments | Method, amount, date, note, against one invoice. Part payments allowed; over-payment and payments on drafts are rejected. Invoice flips to Paid at zero balance. |
| Finance lead | `/` for staff: active subscriptions, MRR, collected vs invoiced for a date range, outstanding, overdue, six-month chart, overdue chase list. Every list is server-paginated with filters. |

### Why nothing is billed twice or skipped

Each subscription has a billing cursor (`billing_anchor` + `periods_billed`). The invoice and the cursor move in the
same transaction. The database also enforces a unique index on `(subscription, period_start)` for non-cancelled
invoices, so two overlapping runs cannot both bill a period. If the system was down, the next run bills every period
that came due, oldest first. Periods are measured from the anchor, so a monthly plan starting on the 31st bills
Jan 31, Feb 28, Mar 31 with no drift. Each subscription commits on its own, so one failure never blocks the batch and
is reported in the run result.

### Performance

Measured on SQLite with 5,000 subscriptions, ~8,700 invoices (2,557 overdue) and ~6,000 payments. Every list, detail
and report endpoint, including the dashboard summary, took **9–27 ms** server-side (in-process client, worst case 27 ms)
and **0.23–0.40 s** end to end over HTTP with curl on Windows, most of which is connection overhead. Both are far inside
the 2 s target. Lists are paginated in SQL and built from column queries; reports are single aggregate queries. Indexes
cover `(status, due_date)`, `(status, next_billing_date)` and the foreign keys. I could not run Postgres on the machine
this was built on, so these are SQLite numbers; the code uses only portable SQL and the partial unique index is declared
for both databases. A billing run is a batch job, not a page: 8,700 invoices for 5,000 subscriptions took about two
minutes on SQLite, each subscription committed separately.

## Decisions and assumptions worth knowing

The brief leaves some things open. These are the calls made, so they can be changed deliberately:

- **Plan price is a plan fee.** It is billed as its own line every period, on top of the product lines. Use 0 if a plan is
  just a cadence. Product lines use product price + variant extra price (staff may negotiate a line price; customers cannot).
- **Billing is in advance**, on the period's first day. A subscription expires on its expiry date; a period that would
  start on or after it is not billed.
- **Discounts:** the best single discount per line (no stacking between product discounts), then the best whole-subscription
  discount on what remains, spread across lines so tax is computed on the discounted amount. A fixed amount comes off once
  per line (product scope) or once per invoice (subscription scope) and never below zero.
- **Pause freezes the clock.** Paused time is not billed and is added to the expiry; billing resumes with the paid-for time
  that was left. **Renew** extends the expiry by the original term length.
- **Overdue is derived, never stored:** a confirmed invoice past its due date with a balance. It cannot go stale.
- **Cancelled invoices** free their period. By default they are not re-billed (a deliberate write-off); "cancel with
  re-bill" rewinds the cursor, only for the latest period, so there is never a gap.
- **Customers** can browse plans, create their own quotation, confirm it, and pause/renew/close where the plan allows.
  They do not choose payment terms. Staff can create a customer first; when that person later registers with the same
  email they are linked to it instead of getting a duplicate.
- **Currency** is shown as INR.

## Not built

- Online card payments: payments are recorded by the team, as the brief describes. There is no gateway.
- Real email: `services/mail.py` writes to a log table. Swap that one function for SMTP or a provider.
- Database migrations: tables are created on startup. Alembic is the next step for a real deployment.
- Login rate limiting and refresh tokens.

## Submission checklist (hackathon portal)

Keep all code on a single branch, add your mentor's GitHub id as a collaborator, and have the team leader submit the
repo link and the demo video.
