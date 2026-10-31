from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .. import deps
from .. import models as m
from ..db import get_db
from ..deps import STAFF_UP, current_user, customer_id_of, page_args
from ..schemas import (BillingRunIn, InvoiceLineOut, InvoiceOut, InvoiceRow, PaymentIn, PaymentOut)
from ..services import billing as svc
from ..services.dates import PERIODS_PER_MONTH
from ..services.subscriptions import DomainError

router = APIRouter(tags=["billing"])
I, C, S = m.Invoice, m.Customer, m.Subscription


def _domain(fn):
    try:
        return fn()
    except DomainError as e:
        raise HTTPException(e.status, e.message)


def _row(r, today: date) -> InvoiceRow:
    """One invoice list row from a column query. 'overdue' is derived, never stored, so it can
    never go stale: a confirmed invoice past its due date with a balance."""
    balance = r.total - r.amount_paid
    overdue = r.status == m.INV_CONFIRMED and r.due_date < today and balance > 0
    return InvoiceRow(
        id=r.id, number=r.number, status=r.status, display_status="overdue" if overdue else r.status,
        subscription_id=r.subscription_id, subscription_number=r.subscription_number,
        customer_id=r.customer_id, customer_name=r.customer_name, issue_date=r.issue_date,
        due_date=r.due_date, period_start=r.period_start, period_end=r.period_end, total=r.total,
        amount_paid=r.amount_paid, balance=balance, days_overdue=(today - r.due_date).days if overdue else 0)


def _cols():
    return (I.id, I.number, I.status, I.subscription_id, S.number.label("subscription_number"),
            I.customer_id, C.name.label("customer_name"), I.issue_date, I.due_date, I.period_start,
            I.period_end, I.total, I.amount_paid)


def _visible(stmt, user: m.User, db: Session):
    if user.role == m.CUSTOMER:
        # Customers never see drafts or cancelled invoices, only what has actually been issued.
        stmt = stmt.where(I.customer_id == customer_id_of(db, user),
                          I.status.in_([m.INV_CONFIRMED, m.INV_PAID]))
    return stmt


def overdue_clause(today: date):
    return (I.status == m.INV_CONFIRMED) & (I.due_date < today)


@router.get("/invoices")
def list_invoices(status: str | None = None, customer_id: int | None = None, subscription_id: int | None = None,
                  q: str | None = None, due_before: date | None = None, page: int = 1, page_size: int = 25,
                  user=Depends(current_user), db: Session = Depends(get_db)):
    page, page_size = page_args(page, page_size)
    today = deps.today()
    stmt = select(*_cols()).join(C, C.id == I.customer_id).join(S, S.id == I.subscription_id)
    stmt = _visible(stmt, user, db)
    if status == "overdue":
        stmt = stmt.where(overdue_clause(today))
    elif status == "outstanding":
        stmt = stmt.where(I.status == m.INV_CONFIRMED)
    elif status:
        stmt = stmt.where(I.status == status)
    if customer_id and user.role != m.CUSTOMER:
        stmt = stmt.where(I.customer_id == customer_id)
    if subscription_id:
        stmt = stmt.where(I.subscription_id == subscription_id)
    if due_before:
        stmt = stmt.where(I.due_date <= due_before)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(I.number).like(like) | func.lower(C.name).like(like))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = I.due_date.asc() if status in ("overdue", "outstanding") else I.id.desc()
    rows = db.execute(stmt.order_by(order, I.id).limit(page_size).offset((page - 1) * page_size)).all()
    return {"items": [_row(r, today) for r in rows], "total": total, "page": page, "page_size": page_size}


def _detail(db: Session, id_: int, user: m.User) -> InvoiceOut:
    stmt = _visible(select(*_cols()).join(C, C.id == I.customer_id).join(S, S.id == I.subscription_id)
                    .where(I.id == id_), user, db)
    r = db.execute(stmt).first()
    if not r:
        raise HTTPException(404, "Invoice not found")
    inv = db.get(m.Invoice, id_)
    row = _row(r, deps.today())
    return InvoiceOut(**row.model_dump(), customer_email=inv.customer.email,
                      customer_address=inv.customer.address, subtotal=inv.subtotal,
                      discount_total=inv.discount_total, tax_total=inv.tax_total, sent_at=inv.sent_at,
                      lines=[InvoiceLineOut.model_validate(l) for l in inv.lines],
                      payments=[PaymentOut.model_validate(p) for p in inv.payments])


@router.get("/invoices/{id}", response_model=InvoiceOut)
def get_invoice(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    return _detail(db, id, user)


def _inv(db: Session, id_: int) -> m.Invoice:
    inv = db.get(m.Invoice, id_, with_for_update=True)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


@router.post("/invoices/{id}/confirm", response_model=InvoiceOut)
def confirm(id: int, user=Depends(STAFF_UP), db: Session = Depends(get_db)):
    inv = _inv(db, id)
    _domain(lambda: svc.confirm_invoice(inv))
    db.commit()
    return _detail(db, id, user)


@router.post("/invoices/{id}/cancel", response_model=InvoiceOut)
def cancel(id: int, rebill: bool = False, user=Depends(STAFF_UP), db: Session = Depends(get_db)):
    inv = _inv(db, id)
    _domain(lambda: svc.cancel_invoice(db, inv, rebill))
    db.commit()
    return _detail(db, id, user)


@router.post("/invoices/{id}/send", response_model=InvoiceOut)
def send(id: int, user=Depends(STAFF_UP), db: Session = Depends(get_db)):
    inv = _inv(db, id)
    number = db.scalar(select(S.number).where(S.id == inv.subscription_id))
    _domain(lambda: svc.send_invoice(db, inv, number))
    db.commit()
    return _detail(db, id, user)


@router.post("/invoices/confirm-drafts")
def confirm_all_drafts(_=Depends(STAFF_UP), db: Session = Depends(get_db)):
    """Confirm every draft in one go: the normal follow-up to a billing run."""
    ids = db.scalars(select(I.id).where(I.status == m.INV_DRAFT).order_by(I.id)).all()
    for i in ids:
        inv = db.get(m.Invoice, i, with_for_update=True)
        if inv.status == m.INV_DRAFT:
            svc.confirm_invoice(inv)
    db.commit()
    return {"confirmed": len(ids)}


@router.post("/billing/run")
def run(body: BillingRunIn, _=Depends(STAFF_UP), db: Session = Depends(get_db)):
    r = svc.run_billing(db, body.as_of or deps.today(), body.auto_confirm)
    return r.__dict__


@router.get("/billing/due")
def due_preview(_=Depends(STAFF_UP), db: Session = Depends(get_db)):
    """How many subscriptions a run would pick up right now."""
    today = deps.today()
    n = db.scalar(select(func.count()).select_from(S).where(
        S.status == m.ACTIVE, S.next_billing_date <= today, S.next_billing_date < S.expiry_date))
    drafts = db.scalar(select(func.count()).select_from(I).where(I.status == m.INV_DRAFT))
    return {"subscriptions_due": n, "draft_invoices": drafts}


# ---------- payments ----------
@router.post("/invoices/{id}/payments", response_model=InvoiceOut, status_code=201)
def add_payment(id: int, body: PaymentIn, user=Depends(STAFF_UP), db: Session = Depends(get_db)):
    _domain(lambda: svc.record_payment(db, id, user, body.method, body.amount, body.paid_on, body.note, deps.today()))
    db.commit()
    return _detail(db, id, user)


@router.get("/payments")
def list_payments(method: str | None = None, date_from: date | None = None, date_to: date | None = None,
                  page: int = 1, page_size: int = 25, _=Depends(STAFF_UP), db: Session = Depends(get_db)):
    page, page_size = page_args(page, page_size)
    P = m.Payment
    stmt = (select(P.id, P.invoice_id, I.number.label("invoice_number"), C.name.label("customer_name"),
                   P.method, P.amount, P.paid_on, P.note)
            .join(I, I.id == P.invoice_id).join(C, C.id == I.customer_id))
    if method:
        stmt = stmt.where(P.method == method)
    if date_from:
        stmt = stmt.where(P.paid_on >= date_from)
    if date_to:
        stmt = stmt.where(P.paid_on <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(P.paid_on.desc(), P.id.desc()).limit(page_size)
                      .offset((page - 1) * page_size)).all()
    return {"items": [dict(r._mapping) for r in rows], "total": total, "page": page, "page_size": page_size}


# ---------- reports ----------
@router.get("/reports/summary")
def summary(date_from: date | None = None, date_to: date | None = None,
            _=Depends(STAFF_UP), db: Session = Depends(get_db)):
    """Everything the finance lead asked for, in a handful of aggregate queries (no row loops)."""
    today = deps.today()
    date_to = date_to or today
    date_from = date_from or date_to.replace(day=1)

    by_status = dict(db.execute(select(S.status, func.count()).group_by(S.status)).all())

    # Monthly recurring revenue: each active subscription's per-period amount normalised to a month.
    factor = case(*[(m.Plan.interval == k, v) for k, v in PERIODS_PER_MONTH.items()], else_=1.0)
    mrr = db.scalar(select(func.coalesce(func.sum(S.recurring_amount * factor), 0))
                    .join(m.Plan, m.Plan.id == S.plan_id).where(S.status == m.ACTIVE)) or 0

    collected = db.scalar(select(func.coalesce(func.sum(m.Payment.amount), 0)).where(
        m.Payment.paid_on >= date_from, m.Payment.paid_on <= date_to)) or Decimal(0)
    billed = db.scalar(select(func.coalesce(func.sum(I.total), 0)).where(
        I.status.in_([m.INV_CONFIRMED, m.INV_PAID]), I.issue_date >= date_from, I.issue_date <= date_to)) or Decimal(0)

    # Receivables are a point-in-time figure over every issued invoice, not limited to the range.
    owed, owed_n = db.execute(select(func.coalesce(func.sum(I.total - I.amount_paid), 0), func.count())
                              .where(I.status == m.INV_CONFIRMED)).one()
    od, od_n = db.execute(select(func.coalesce(func.sum(I.total - I.amount_paid), 0), func.count())
                          .where(overdue_clause(today))).one()
    invoice_counts = dict(db.execute(select(I.status, func.count()).group_by(I.status)).all())

    return {
        "as_of": today, "date_from": date_from, "date_to": date_to,
        "active_subscriptions": by_status.get(m.ACTIVE, 0),
        "subscriptions_by_status": by_status,
        "mrr": round(Decimal(str(mrr)), 2), "arr": round(Decimal(str(mrr)) * 12, 2),
        "billed_in_range": billed, "collected_in_range": collected,
        "outstanding_amount": owed, "outstanding_count": owed_n,
        "overdue_amount": od, "overdue_count": od_n,
        "invoices_by_status": invoice_counts,
    }


@router.get("/reports/revenue-series")
def revenue_series(months: int = 12, _=Depends(STAFF_UP), db: Session = Depends(get_db)):
    """Cash collected vs invoiced per month, oldest first."""
    months = min(max(months, 1), 36)
    today = deps.today()
    first = date(today.year, today.month, 1)
    keys = []
    y, mo = first.year, first.month
    for _i in range(months):
        keys.append((y, mo))
        mo -= 1
        if mo == 0:
            y, mo = y - 1, 12
    keys.reverse()
    start = date(keys[0][0], keys[0][1], 1)
    # Group in Python over a pre-aggregated per-day result: portable across Postgres and SQLite.
    paid = {}
    for d, amt in db.execute(select(m.Payment.paid_on, func.sum(m.Payment.amount))
                             .where(m.Payment.paid_on >= start).group_by(m.Payment.paid_on)):
        paid[(d.year, d.month)] = paid.get((d.year, d.month), Decimal(0)) + amt
    billed = {}
    for d, amt in db.execute(select(I.issue_date, func.sum(I.total))
                             .where(I.issue_date >= start, I.status.in_([m.INV_CONFIRMED, m.INV_PAID]))
                             .group_by(I.issue_date)):
        billed[(d.year, d.month)] = billed.get((d.year, d.month), Decimal(0)) + amt
    return [{"month": f"{y}-{mo:02d}", "collected": paid.get((y, mo), Decimal(0)),
             "billed": billed.get((y, mo), Decimal(0))} for y, mo in keys]
