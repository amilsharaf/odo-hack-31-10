"""Recurring billing and the invoice/payment lifecycle.

Why nothing is billed twice or skipped:
  * Each subscription carries a cursor (billing_anchor + periods_billed). An invoice is created and
    the cursor advanced in the same transaction, so they cannot disagree.
  * The database also holds a unique index on (subscription, period_start) for live invoices. If
    two runs race, the loser hits the index and is skipped instead of double-billing.
  * Falling behind is safe: a run bills every period that has come due, oldest first.
Each subscription commits on its own, so one bad record never blocks the other few hundred.
"""
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from . import pricing
from .dates import advance
from .mail import send_mail
from .pricing import LineIn, Rule, q
from .subscriptions import DomainError, line_rate

log = logging.getLogger("brightloop.billing")


@dataclass
class RunResult:
    as_of: date
    activated: int = 0
    quotes_expired: int = 0
    subscriptions_billed: int = 0
    invoices_created: int = 0
    already_billed: int = 0
    closed: int = 0
    errors: list[str] = field(default_factory=list)


def load_rules(db: Session, on: date) -> list[Rule]:
    rows = db.scalars(select(m.Discount).where(
        m.Discount.active.is_(True),
        or_(m.Discount.start_date.is_(None), m.Discount.start_date <= on),
        or_(m.Discount.end_date.is_(None), m.Discount.end_date >= on),
        or_(m.Discount.usage_limit.is_(None), m.Discount.used_count < m.Discount.usage_limit),
    )).all()
    return [Rule(id=d.id, name=d.name, kind=d.kind, value=d.value, scope=d.scope,
                 min_purchase=d.min_purchase, min_quantity=d.min_quantity,
                 product_ids=frozenset(p.id for p in d.products)) for d in rows]


def _claim(db: Session, discount_id: int) -> bool:
    """Atomically take one use of a discount. False if the limit was reached meanwhile."""
    res = db.execute(update(m.Discount).where(
        m.Discount.id == discount_id,
        or_(m.Discount.usage_limit.is_(None), m.Discount.used_count < m.Discount.usage_limit),
    ).values(used_count=m.Discount.used_count + 1))
    return res.rowcount == 1


def _lines_for(sub: m.Subscription) -> list[LineIn]:
    lines: list[LineIn] = []
    plan = sub.plan
    if plan.price > 0:
        rate = plan.tax.rate if plan.tax and plan.tax.active else Decimal(0)
        lines.append(LineIn(f"{plan.name} plan ({plan.interval})", 1, plan.price, rate, None))
    for l in sub.lines:
        label = l.product.name + (f" ({l.variant.attribute}: {l.variant.value})" if l.variant else "")
        lines.append(LineIn(label, l.quantity, l.unit_price, line_rate(l), l.product_id))
    return lines


def build_invoice(db: Session, sub: m.Subscription, start: date, end: date, today: date,
                  rules: list[Rule], auto_confirm: bool) -> m.Invoice:
    excluded: set[int] = set()
    while True:
        priced = pricing.price(_lines_for(sub), [r for r in rules if r.id not in excluded])
        claimed: list[int] = []
        lost = None
        for i in sorted(priced.used):
            if _claim(db, i):
                claimed.append(i)
            else:
                lost = i
                break
        if lost is None:
            break
        # Someone took the last allowed use after the rules were loaded. Hand back what this pass
        # claimed and reprice without that discount.
        for i in claimed:
            db.execute(update(m.Discount).where(m.Discount.id == i, m.Discount.used_count > 0)
                       .values(used_count=m.Discount.used_count - 1))
        excluded.add(lost)

    days = sub.payment_term.days if sub.payment_term else 0
    inv = m.Invoice(
        subscription_id=sub.id, customer_id=sub.customer_id, status=m.INV_DRAFT, issue_date=today,
        due_date=today + timedelta(days=days), period_start=start, period_end=end,
        subtotal=priced.subtotal, discount_total=priced.discount_total, tax_total=priced.tax_total,
        total=priced.total)
    for lo in priced.lines:
        inv.lines.append(m.InvoiceLine(
            product_id=lo.src.product_id, discount_id=lo.discount_id, description=lo.src.description,
            quantity=lo.src.quantity, unit_price=lo.src.unit_price, gross=lo.gross,
            discount_amount=lo.discount, tax_rate=lo.src.tax_rate, tax_amount=lo.tax, total=lo.total))
    db.add(inv)
    db.flush()
    inv.number = f"INV-{today.year}-{inv.id:06d}"
    for i in priced.used:
        db.add(m.InvoiceDiscountUse(invoice_id=inv.id, discount_id=i))
    db.flush()
    if auto_confirm:
        confirm_invoice(inv)
    return inv


def _period_exists(db: Session, sub_id: int, start: date) -> bool:
    return db.scalar(select(exists().where(
        m.Invoice.subscription_id == sub_id, m.Invoice.period_start == start,
        m.Invoice.status != m.INV_CANCELLED))) is True


def bill_subscription(db: Session, sub_id: int, today: date, rules: list[Rule],
                      auto_confirm: bool, res: RunResult) -> None:
    sub = db.get(m.Subscription, sub_id, with_for_update=True)
    if not sub or sub.status != m.ACTIVE:
        return
    made = 0
    while sub.next_billing_date <= today and sub.next_billing_date < sub.expiry_date:
        start = sub.next_billing_date
        nxt = advance(sub.billing_anchor, sub.plan.interval, sub.periods_billed + 1)
        if _period_exists(db, sub.id, start):
            res.already_billed += 1
        else:
            build_invoice(db, sub, start, nxt - timedelta(days=1), today, rules, auto_confirm)
            made += 1
        sub.periods_billed += 1
        sub.next_billing_date = nxt
    db.commit()
    if made:
        res.subscriptions_billed += 1
        res.invoices_created += made


def run_billing(db: Session, today: date, auto_confirm: bool = False) -> RunResult:
    res = RunResult(as_of=today)

    res.activated = db.execute(update(m.Subscription).where(
        m.Subscription.status == m.CONFIRMED, m.Subscription.start_date <= today
    ).values(status=m.ACTIVE)).rowcount
    res.quotes_expired = db.execute(update(m.Subscription).where(
        m.Subscription.status == m.QUOTATION, m.Subscription.quote_valid_until < today
    ).values(status=m.CLOSED)).rowcount
    db.commit()

    rules = load_rules(db, today)
    due = db.scalars(select(m.Subscription.id).where(
        m.Subscription.status == m.ACTIVE,
        m.Subscription.next_billing_date <= today,
        m.Subscription.next_billing_date < m.Subscription.expiry_date,
    ).order_by(m.Subscription.id)).all()
    for sid in due:
        try:
            bill_subscription(db, sid, today, rules, auto_confirm, res)
        except IntegrityError:
            db.rollback()  # lost a race to another run: that period is already billed
            res.already_billed += 1
        except Exception as e:  # noqa: BLE001 - isolate one subscription's failure from the batch
            db.rollback()
            log.exception("billing failed for subscription %s", sid)
            res.errors.append(f"subscription {sid}: {e}")

    # Plans that close on their own: once the term is over and every period has been billed.
    auto_plans = select(m.Plan.id).where(m.Plan.auto_close.is_(True))
    res.closed = db.execute(update(m.Subscription).where(
        m.Subscription.status == m.ACTIVE, m.Subscription.plan_id.in_(auto_plans),
        m.Subscription.expiry_date <= today, m.Subscription.next_billing_date >= m.Subscription.expiry_date,
    ).values(status=m.CLOSED)).rowcount
    db.commit()
    return res


# ---------------- invoice lifecycle ----------------
def confirm_invoice(inv: m.Invoice) -> None:
    if inv.status != m.INV_DRAFT:
        raise DomainError("Only a draft invoice can be confirmed", 409)
    inv.status = m.INV_CONFIRMED
    if inv.total <= 0:  # fully discounted: nothing to collect
        inv.status = m.INV_PAID


def cancel_invoice(db: Session, inv: m.Invoice, rebill: bool = False) -> None:
    if inv.status in (m.INV_PAID, m.INV_CANCELLED) or inv.amount_paid > 0:
        raise DomainError("This invoice has payments or is already closed and cannot be cancelled", 409)
    inv.status = m.INV_CANCELLED
    uses = db.scalars(select(m.InvoiceDiscountUse).where(m.InvoiceDiscountUse.invoice_id == inv.id)).all()
    for u in uses:  # the discount use goes back; a re-bill will take it again
        db.execute(update(m.Discount).where(m.Discount.id == u.discount_id, m.Discount.used_count > 0)
                   .values(used_count=m.Discount.used_count - 1))
        db.delete(u)
    if rebill:
        sub = db.get(m.Subscription, inv.subscription_id, with_for_update=True)
        last_start = advance(sub.billing_anchor, sub.plan.interval, sub.periods_billed - 1)
        # Only the most recent period can be rewound without leaving a gap in the sequence.
        if sub.periods_billed > 0 and inv.period_start == last_start:
            sub.periods_billed -= 1
            sub.next_billing_date = last_start
        else:
            raise DomainError("Only the latest billed period can be re-billed", 409)


def record_payment(db: Session, inv_id: int, user: m.User, method: str, amount: Decimal,
                   paid_on: date | None, note: str | None, today: date) -> m.Payment:
    inv = db.get(m.Invoice, inv_id, with_for_update=True)  # serialises concurrent payments
    if not inv:
        raise DomainError("Invoice not found", 404)
    if inv.status != m.INV_CONFIRMED:
        raise DomainError("Payments can only be recorded against a confirmed invoice", 409)
    amount = q(amount)
    if amount > inv.balance:
        raise DomainError(f"Payment exceeds the outstanding balance of {inv.balance}", 422)
    when = paid_on or today
    if when > today:
        raise DomainError("Payment date cannot be in the future", 422)
    pay = m.Payment(invoice_id=inv.id, method=method, amount=amount, paid_on=when, note=note,
                    recorded_by=user.id)
    db.add(pay)
    inv.amount_paid += amount
    if inv.balance <= 0:
        inv.status = m.INV_PAID
    db.flush()
    return pay


def send_invoice(db: Session, inv: m.Invoice, sub_number: str | None) -> None:
    if inv.status not in (m.INV_CONFIRMED, m.INV_PAID):
        raise DomainError("Confirm the invoice before sending it", 409)
    send_mail(db, inv.customer.email, f"Invoice {inv.number} from Brightloop Software",
              f"Hi {inv.customer.name},\n\nInvoice {inv.number} for subscription {sub_number} is "
              f"{inv.total} due on {inv.due_date}.\nBalance: {inv.balance}.\n\nThank you,\nBrightloop")
    inv.sent_at = m.utcnow()
