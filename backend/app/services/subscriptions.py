"""Subscription rules: building lines, validating against the plan, and the lifecycle.

    draft -> quotation -> confirmed -> active -> closed
                                         ⇅
                                       paused

Cancelling before activation always closes. Closing, pausing and renewing something that is
already running are decided by the flags the admin set on its plan.
"""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from .. import models as m
from ..schemas import SubLineIn, SubLineOut, SubscriptionOut
from .dates import advance
from .pricing import q


class DomainError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message, self.status = message, status


EDITABLE = {m.DRAFT, m.QUOTATION}


def check_plan_available(plan: m.Plan, on: date) -> None:
    if not plan.active:
        raise DomainError("This plan is no longer offered")
    if plan.valid_from and on < plan.valid_from:
        raise DomainError(f"This plan is only available from {plan.valid_from}")
    if plan.valid_to and on > plan.valid_to:
        raise DomainError(f"This plan was only available until {plan.valid_to}")


def build_lines(db: Session, plan: m.Plan, lines: list[SubLineIn], allow_price: bool) -> list[m.SubscriptionLine]:
    if not lines:
        raise DomainError("Add at least one product line")
    out = []
    for l in lines:
        product = db.get(m.Product, l.product_id)
        if not product or not product.active:
            raise DomainError(f"Product {l.product_id} is not available")
        variant = None
        if l.variant_id is not None:
            variant = next((v for v in product.variants if v.id == l.variant_id), None)
            if not variant:
                raise DomainError(f"Variant {l.variant_id} does not belong to {product.name}")
        elif product.variants:
            raise DomainError(f"Choose a variant for {product.name}")
        if l.quantity < plan.min_quantity:
            raise DomainError(f"{plan.name} needs a quantity of at least {plan.min_quantity} per line")
        price = product.sales_price + (variant.extra_price if variant else 0)
        if allow_price and l.unit_price is not None:
            price = l.unit_price
        out.append(m.SubscriptionLine(
            product=product, variant=variant, quantity=l.quantity, unit_price=q(price),
            tax_id=product.tax_id))
    return out


def line_rate(line: m.SubscriptionLine) -> Decimal:
    t = line.tax or line.product.tax
    return t.rate if t and t.active else Decimal(0)


def recalc(sub: m.Subscription) -> None:
    sub.recurring_amount = q(sub.plan.price + sum((q(l.unit_price * l.quantity) for l in sub.lines), Decimal(0)))


def create(db: Session, *, user: m.User, customer_id: int, data, today: date) -> m.Subscription:
    template = db.get(m.QuotationTemplate, data.template_id) if data.template_id else None
    if data.template_id and not template:
        raise DomainError("Quotation template not found", 404)
    plan_id = data.plan_id or (template.plan_id if template else None)
    plan = db.get(m.Plan, plan_id) if plan_id else None
    if not plan:
        raise DomainError("Choose a plan")
    start = data.start_date or today
    check_plan_available(plan, start)

    line_inputs = data.lines
    if line_inputs is None and template:
        line_inputs = [SubLineIn(product_id=t.product_id, variant_id=t.variant_id,
                                 quantity=max(t.quantity, plan.min_quantity)) for t in template.lines]
    lines = build_lines(db, plan, line_inputs or [], allow_price=user.role != m.CUSTOMER)

    expiry = data.expiry_date or advance(start, "yearly", 1)
    if expiry <= start:
        raise DomainError("Expiry date must be after the start date")
    # Payment terms are a commercial decision: customers do not set their own. Staff can add them
    # while the quotation is still open.
    term_id = data.payment_term_id if user.role != m.CUSTOMER else None
    term = db.get(m.PaymentTerm, term_id) if term_id else None
    if term_id and not term:
        raise DomainError("Payment term not found", 404)

    sub = m.Subscription(
        customer_id=customer_id, plan=plan, payment_term=term, template_id=template.id if template else None,
        status=m.QUOTATION if (template or user.role == m.CUSTOMER) else m.DRAFT,
        start_date=start, expiry_date=expiry, term_days=(expiry - start).days,
        billing_anchor=start, next_billing_date=start, notes=data.notes, created_by=user.id,
        quote_valid_until=today + timedelta(days=template.validity_days if template else 30))
    sub.lines = lines
    recalc(sub)
    db.add(sub)
    db.flush()
    sub.number = f"SUB-{sub.id:06d}"
    return sub


def update(db: Session, sub: m.Subscription, patch, user: m.User, today: date) -> None:
    if sub.status not in EDITABLE:
        raise DomainError("Only a draft or quotation can be edited", 409)
    if patch.plan_id and patch.plan_id != sub.plan_id:
        plan = db.get(m.Plan, patch.plan_id)
        if not plan:
            raise DomainError("Plan not found", 404)
        sub.plan = plan
    if patch.payment_term_id is not None and user.role != m.CUSTOMER:
        sub.payment_term = db.get(m.PaymentTerm, patch.payment_term_id)
    if patch.start_date:
        sub.start_date = sub.billing_anchor = sub.next_billing_date = patch.start_date
    if patch.expiry_date:
        sub.expiry_date = patch.expiry_date
    if sub.expiry_date <= sub.start_date:
        raise DomainError("Expiry date must be after the start date")
    sub.term_days = (sub.expiry_date - sub.start_date).days
    check_plan_available(sub.plan, sub.start_date)
    if patch.lines is not None:
        sub.lines = build_lines(db, sub.plan, patch.lines, allow_price=user.role != m.CUSTOMER)
    elif patch.plan_id:  # plan changed: existing quantities must still satisfy its minimum
        for l in sub.lines:
            if l.quantity < sub.plan.min_quantity:
                raise DomainError(f"{sub.plan.name} needs a quantity of at least {sub.plan.min_quantity} per line")
    if patch.notes is not None:
        sub.notes = patch.notes
    recalc(sub)


def allowed_actions(sub: m.Subscription, role: str, today: date) -> list[str]:
    staff = role in (m.ADMIN, m.STAFF)
    p, s, acts = sub.plan, sub.status, []
    if s == m.DRAFT and staff:
        acts.append("send_quote")
    if s == m.QUOTATION and (not sub.quote_valid_until or sub.quote_valid_until >= today):
        acts.append("confirm")
    if s == m.CONFIRMED and staff:
        acts.append("activate")
    if s == m.ACTIVE and p.pausable:
        acts.append("pause")
    if s == m.PAUSED:
        acts.append("resume")
    if s == m.ACTIVE and p.renewable:
        acts.append("renew")
    if s in (m.DRAFT, m.QUOTATION, m.CONFIRMED) or (s in (m.ACTIVE, m.PAUSED) and p.closable):
        if not (s == m.DRAFT and not staff):
            acts.append("close")
    return acts


def transition(sub: m.Subscription, action: str, role: str, today: date) -> None:
    if action not in allowed_actions(sub, role, today):
        raise DomainError(f"Cannot {action.replace('_', ' ')} a {sub.status} subscription here", 409)
    if action == "send_quote":
        sub.status = m.QUOTATION
    elif action == "confirm":
        sub.status = m.CONFIRMED
    elif action == "activate":
        sub.status = m.ACTIVE
    elif action == "pause":
        sub.status, sub.paused_on = m.PAUSED, today
    elif action == "resume":
        days = max((today - sub.paused_on).days, 0) if sub.paused_on else 0
        # Paused time is neither billed nor deducted from the term: push everything out by it.
        sub.expiry_date += timedelta(days=days)
        sub.billing_anchor = sub.next_billing_date + timedelta(days=days)
        sub.next_billing_date, sub.periods_billed = sub.billing_anchor, 0
        sub.status, sub.paused_on = m.ACTIVE, None
    elif action == "renew":
        sub.expiry_date += timedelta(days=sub.term_days)
    elif action == "close":
        sub.status = m.CLOSED


def to_out(sub: m.Subscription, role: str, today: date) -> SubscriptionOut:
    lines, subtotal, tax_total = [], Decimal(0), Decimal(0)
    for l in sub.lines:
        net = q(l.unit_price * l.quantity)
        rate = line_rate(l)
        tax = q(net * rate / 100)
        subtotal, tax_total = subtotal + net, tax_total + tax
        t = l.tax or l.product.tax
        lines.append(SubLineOut(
            id=l.id, product_id=l.product_id, product_name=l.product.name, variant_id=l.variant_id,
            variant=f"{l.variant.attribute}: {l.variant.value}" if l.variant else None,
            quantity=l.quantity, unit_price=l.unit_price, tax_id=t.id if t else None,
            tax_name=t.name if t else None, tax_rate=rate, net=net, tax=tax, amount=net + tax))
    fee_tax = q(sub.plan.price * (sub.plan.tax.rate if sub.plan.tax and sub.plan.tax.active else 0) / 100)
    subtotal += sub.plan.price
    tax_total += fee_tax
    return SubscriptionOut(
        id=sub.id, number=sub.number, status=sub.status, customer_id=sub.customer_id,
        customer_name=sub.customer.name, plan_id=sub.plan_id, plan_name=sub.plan.name,
        plan_interval=sub.plan.interval, plan_price=sub.plan.price, payment_term_id=sub.payment_term_id,
        payment_term=sub.payment_term.name if sub.payment_term else None, template_id=sub.template_id,
        start_date=sub.start_date, expiry_date=sub.expiry_date, quote_valid_until=sub.quote_valid_until,
        next_billing_date=sub.next_billing_date, recurring_amount=sub.recurring_amount, notes=sub.notes,
        lines=lines, subtotal=subtotal, tax_total=tax_total, total=subtotal + tax_total,
        allowed_actions=allowed_actions(sub, role, today), created_at=sub.created_at)
