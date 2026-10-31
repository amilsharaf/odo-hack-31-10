"""Demo data.   python seed.py            -> a small, readable Brightloop catalogue and a few customers
               python seed.py --bulk 5000 -> additionally N subscriptions with billed history, for the
                                             "responds in under two seconds" check
"""
import argparse
import random
import time
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app import deps
from app import models as m
from app.db import SessionLocal, engine
from app.security import hash_password
from app.services.billing import run_billing
from app.services.dates import advance

ADMIN = ("admin@brightloop.example.com", "Admin Brightloop", "Admin@12345")
STAFF = ("staff@brightloop.example.com", "Sam Staff", "Staff@12345")
CUSTOMER = ("customer@acme.example.com", "Priya Customer", "Customer@12345")


def reset_and_create() -> None:
    m.Base.metadata.drop_all(engine)
    m.Base.metadata.create_all(engine)


def seed_demo(db) -> dict:
    today = deps.today()
    for email, name, pw in (ADMIN, STAFF):
        db.add(m.User(email=email, name=name, password_hash=hash_password(pw),
                      role=m.ADMIN if email == ADMIN[0] else m.STAFF))
    cu = m.User(email=CUSTOMER[0], name=CUSTOMER[1], password_hash=hash_password(CUSTOMER[2]), role=m.CUSTOMER)
    db.add(cu)
    db.flush()

    gst, reduced, exempt = m.Tax(name="GST 18%", rate=18), m.Tax(name="GST 5%", rate=5), m.Tax(name="Exempt", rate=0)
    db.add_all([gst, reduced, exempt])
    imm, n15, n30 = (m.PaymentTerm(name="Immediate", days=0), m.PaymentTerm(name="Net 15", days=15),
                     m.PaymentTerm(name="Net 30", days=30))
    db.add_all([imm, n15, n30])
    db.flush()

    crm = m.Product(name="Brightloop CRM", type="software", sales_price=1200, cost_price=400, tax_id=gst.id,
                    notes="Core CRM seat.")
    crm.variants = [m.ProductVariant(attribute="Brand", value="Brightloop", extra_price=0),
                    m.ProductVariant(attribute="Brand", value="Odoo", extra_price=560)]
    analytics = m.Product(name="Analytics Add-on", type="addon", sales_price=300, cost_price=90, tax_id=gst.id)
    support = m.Product(name="Premium Support", type="service", sales_price=450, cost_price=200, tax_id=reduced.id)
    storage = m.Product(name="Extra Storage 100GB", type="addon", sales_price=120, cost_price=30, tax_id=gst.id)
    training = m.Product(name="Onboarding Training", type="service", sales_price=2000, cost_price=900, tax_id=exempt.id)
    db.add_all([crm, analytics, support, storage, training])

    starter = m.Plan(name="Starter Monthly", price=0, interval="monthly", min_quantity=1, closable=True,
                     pausable=True, renewable=True, valid_from=today - timedelta(days=365))
    business = m.Plan(name="Business Yearly", price=1000, interval="yearly", min_quantity=5, closable=False,
                      pausable=False, renewable=True, tax_id=gst.id, valid_from=today - timedelta(days=365))
    trial = m.Plan(name="30-Day Pilot", price=100, interval="weekly", min_quantity=1, auto_close=True,
                   closable=True, pausable=False, renewable=False, tax_id=gst.id)
    db.add_all([starter, business, trial])
    db.flush()

    db.add_all([
        m.QuotationTemplate(name="Starter bundle", validity_days=14, plan_id=starter.id, notes="CRM + analytics",
                            lines=[m.TemplateLine(product_id=crm.id, variant_id=crm.variants[0].id, quantity=1),
                                   m.TemplateLine(product_id=analytics.id, quantity=1)]),
        m.QuotationTemplate(name="Enterprise rollout", validity_days=30, plan_id=business.id,
                            lines=[m.TemplateLine(product_id=crm.id, variant_id=crm.variants[1].id, quantity=10),
                                   m.TemplateLine(product_id=support.id, quantity=10),
                                   m.TemplateLine(product_id=training.id, quantity=5)]),
    ])
    seats = m.Discount(name="10% off 10+ CRM seats", kind="percent", value=10, scope="product", min_quantity=10,
                       start_date=today - timedelta(days=30), end_date=today + timedelta(days=365), products=[crm])
    welcome = m.Discount(name="Welcome: 200 off", kind="fixed", value=200, scope="subscription", min_purchase=1000,
                         start_date=today - timedelta(days=30), end_date=today + timedelta(days=180), usage_limit=50)
    db.add_all([seats, welcome])

    acme = m.Customer(user_id=cu.id, name=CUSTOMER[1], email=CUSTOMER[0], company="Acme Retail",
                      phone="+91 98765 43210", address="12 Park Street, Kolkata")
    globex = m.Customer(name="Globex Corp", email="billing@globex.example.com", company="Globex Corp",
                        address="500 Market Road, Pune")
    db.add_all([acme, globex])
    db.commit()
    return {"admin": ADMIN, "staff": STAFF, "customer": CUSTOMER}


def bill_through_history(db, since):
    """Run billing week by week, as a daily job would have, so issue and due dates are realistic."""
    today = deps.today()
    d, total = since, 0
    while d <= today:
        total += run_billing(db, d, auto_confirm=True).invoices_created
        d += timedelta(days=7)
    total += run_billing(db, today, auto_confirm=True).invoices_created
    return total


def settle(db, rnd, paid=0.62, partial=0.08):
    """Pay most confirmed invoices in full (some late), a few partly, leave the rest open."""
    today = deps.today()
    invs = db.execute(select(m.Invoice.id, m.Invoice.total, m.Invoice.issue_date, m.Invoice.due_date)
                      .where(m.Invoice.status == m.INV_CONFIRMED)).all()
    pays, full, part = [], [], []
    for iid, total, issued, due in invs:
        r = rnd.random()
        if r < paid:
            when = min(today, issued + timedelta(days=rnd.randint(0, 25)))
            pays.append(m.Payment(invoice_id=iid, method=rnd.choice(m.PAYMENT_METHODS), amount=total, paid_on=when))
            full.append(iid)
        elif r < paid + partial:
            amt = (total / 2).quantize(Decimal("0.01"))
            pays.append(m.Payment(invoice_id=iid, method="bank_transfer", amount=amt, paid_on=issued,
                                  note="Part payment"))
            part.append((iid, amt))
    db.add_all(pays)
    db.flush()
    for iid in full:
        inv = db.get(m.Invoice, iid)
        inv.amount_paid, inv.status = inv.total, m.INV_PAID
    for iid, amt in part:
        db.get(m.Invoice, iid).amount_paid = amt
    db.commit()
    return len(pays)


def add_sub(db, customer, plan, term, lines, start, status=m.ACTIVE, days=None):
    expiry = start + timedelta(days=days) if days else advance(start, "yearly", 1)
    s = m.Subscription(customer_id=customer.id, plan=plan, payment_term=term, status=status, start_date=start,
                       expiry_date=expiry, term_days=(expiry - start).days, billing_anchor=start,
                       next_billing_date=start, quote_valid_until=deps.today() + timedelta(days=30))
    for product, variant, qty in lines:
        s.lines.append(m.SubscriptionLine(product=product, variant=variant, quantity=max(qty, plan.min_quantity),
                                          unit_price=product.sales_price + (variant.extra_price if variant else 0),
                                          tax_id=product.tax_id))
    s.recurring_amount = plan.price + sum(l.unit_price * l.quantity for l in s.lines)
    db.add(s)
    db.flush()
    s.number = f"SUB-{s.id:06d}"
    return s


def seed_story(db) -> None:
    """A handful of subscriptions in different states, so every screen has something real on it."""
    rnd = random.Random(11)
    today = deps.today()
    acme, globex = db.scalars(select(m.Customer).order_by(m.Customer.id)).all()
    starter, business, pilot = db.scalars(select(m.Plan).order_by(m.Plan.id)).all()
    n15, n30 = db.scalars(select(m.PaymentTerm).where(m.PaymentTerm.days > 0).order_by(m.PaymentTerm.days)).all()
    crm, analytics, support, storage, training = db.scalars(select(m.Product).order_by(m.Product.id)).unique().all()
    odoo, brightloop = crm.variants[1], crm.variants[0]
    extra = [m.Customer(name=n, email=e, company=c) for n, e, c in (
        ("Meera Nair", "meera@kitebakery.example.com", "Kite Bakery"), ("Arjun Rao", "arjun@northwind.example.com", "Northwind Labs"),
        ("Tara Shah", "tara@lumen.example.com", "Lumen Studio"))]
    db.add_all(extra)
    db.flush()
    add_sub(db, acme, starter, n15, [(crm, brightloop, 3), (analytics, None, 3)], today - timedelta(days=75))
    add_sub(db, globex, business, n30, [(crm, odoo, 12), (support, None, 12), (training, None, 5)], today - timedelta(days=100))
    add_sub(db, extra[0], starter, n15, [(crm, brightloop, 2), (storage, None, 2)], today - timedelta(days=40))
    add_sub(db, extra[1], pilot, n15, [(crm, brightloop, 1)], today - timedelta(days=21), days=30)
    add_sub(db, extra[2], starter, n30, [(crm, brightloop, 4)], today - timedelta(days=95))
    paused = add_sub(db, acme, starter, n15, [(storage, None, 4)], today - timedelta(days=50))
    paused.status, paused.paused_on = m.PAUSED, today - timedelta(days=12)
    add_sub(db, extra[1], business, n30, [(crm, odoo, 6)], today, status=m.QUOTATION)
    add_sub(db, extra[2], starter, n15, [(analytics, None, 2)], today, status=m.DRAFT)
    db.commit()
    n = bill_through_history(db, today - timedelta(days=100))
    settle(db, rnd, paid=0.6, partial=0.1)
    print(f"story data: {n} invoices")


def seed_bulk(db, n: int) -> None:
    rnd = random.Random(7)
    today = deps.today()
    plans = db.scalars(select(m.Plan).where(m.Plan.interval.in_(["monthly", "yearly"]))).all()
    products = db.scalars(select(m.Product)).unique().all()
    terms = db.scalars(select(m.PaymentTerm)).all()
    t0 = time.time()
    first_id = (db.scalar(select(func.max(m.Customer.id))) or 0) + 1
    db.add_all([m.Customer(name=f"Customer {i:05d}", email=f"c{i}@bulk.example.com", company=f"Company {i}")
                for i in range(n)])
    db.flush()
    for i in range(n):
        plan = rnd.choice(plans)
        start = today - timedelta(days=rnd.randint(0, 120))
        expiry = advance(start, "yearly", 1)
        s = m.Subscription(
            customer_id=first_id + i, plan=plan, payment_term=rnd.choice(terms), status=m.ACTIVE,
            start_date=start, expiry_date=expiry, term_days=(expiry - start).days, billing_anchor=start,
            next_billing_date=start, number=f"BULK-{i:06d}")
        for p in rnd.sample(products, rnd.randint(1, 3)):
            v = p.variants[0] if p.variants else None
            s.lines.append(m.SubscriptionLine(product=p, variant=v, quantity=max(plan.min_quantity, rnd.randint(1, 8)),
                                              unit_price=p.sales_price, tax_id=p.tax_id))
        s.recurring_amount = plan.price + sum(l.unit_price * l.quantity for l in s.lines)
        db.add(s)
        if i % 500 == 499:
            db.commit()
    db.commit()
    print(f"created {n} subscriptions in {time.time() - t0:.1f}s; billing...")
    t1 = time.time()
    made = bill_through_history(db, today - timedelta(days=120))
    print(f"billing: {made} invoices in {time.time() - t1:.1f}s")
    print(f"seeded {settle(db, rnd)} payments")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bulk", type=int, default=0)
    ap.add_argument("--keep", action="store_true", help="do not wipe existing data first")
    a = ap.parse_args()
    if not a.keep:
        reset_and_create()
    with SessionLocal() as db:
        if not a.keep:
            seed_demo(db)
            seed_story(db)
        if a.bulk:
            seed_bulk(db, a.bulk)
    print("Seeded. Logins:\n  admin    ", ADMIN[0], ADMIN[2], "\n  staff    ", STAFF[0], STAFF[2],
          "\n  customer ", CUSTOMER[0], CUSTOMER[2])
