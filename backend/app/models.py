"""Data model.

Money is Numeric(12, 2) end to end. Statuses are plain strings validated at the API edge so the
schema stays portable between Postgres and SQLite.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Table, Text, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

Money = Numeric(12, 2)

# roles
ADMIN, STAFF, CUSTOMER = "admin", "staff", "customer"
# subscription statuses
DRAFT, QUOTATION, CONFIRMED, ACTIVE, PAUSED, CLOSED = (
    "draft", "quotation", "confirmed", "active", "paused", "closed")
# invoice statuses
INV_DRAFT, INV_CONFIRMED, INV_PAID, INV_CANCELLED = "draft", "confirmed", "paid", "cancelled"
INTERVALS = ("daily", "weekly", "monthly", "yearly")
PAYMENT_METHODS = ("card", "bank_transfer", "cash", "upi", "cheque")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)  # stored lowercased
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10), default=CUSTOMER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PasswordReset(Base):
    __tablename__ = "password_resets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 of the emailed token
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MailLog(Base):
    """Outgoing mail is written here (and logged) instead of leaving through SMTP."""
    __tablename__ = "mail_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    to: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), index=True)
    company: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Tax(Base):
    __tablename__ = "taxes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))  # percent
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PaymentTerm(Base):
    __tablename__ = "payment_terms"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    days: Mapped[int] = mapped_column(Integer)  # invoice due this many days after issue


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    type: Mapped[str] = mapped_column(String(30), default="service")
    sales_price: Mapped[Decimal] = mapped_column(Money)
    cost_price: Mapped[Decimal] = mapped_column(Money, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    tax_id: Mapped[int | None] = mapped_column(ForeignKey("taxes.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    tax: Mapped[Tax | None] = relationship(lazy="joined")
    variants: Mapped[list["ProductVariant"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="ProductVariant.id")


class ProductVariant(Base):
    """e.g. attribute='Brand', value='Odoo', extra_price=560 -> that variant sells at base + 560."""
    __tablename__ = "product_variants"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    attribute: Mapped[str] = mapped_column(String(60))
    value: Mapped[str] = mapped_column(String(60))
    extra_price: Mapped[Decimal] = mapped_column(Money, default=0)


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    price: Mapped[Decimal] = mapped_column(Money)  # base fee per billing period, billed as its own line
    interval: Mapped[str] = mapped_column(String(10))
    min_quantity: Mapped[int] = mapped_column(Integer, default=1)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    tax_id: Mapped[int | None] = mapped_column(ForeignKey("taxes.id"))
    # Admin decides, plan by plan, what can happen to a subscription on it.
    auto_close: Mapped[bool] = mapped_column(Boolean, default=False)
    closable: Mapped[bool] = mapped_column(Boolean, default=True)
    pausable: Mapped[bool] = mapped_column(Boolean, default=False)
    renewable: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    tax: Mapped[Tax | None] = relationship(lazy="joined")


class QuotationTemplate(Base):
    __tablename__ = "quotation_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    validity_days: Mapped[int] = mapped_column(Integer, default=30)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[Plan] = relationship(lazy="joined")
    lines: Mapped[list["TemplateLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="TemplateLine.id")


class TemplateLine(Base):
    __tablename__ = "template_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("quotation_templates.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)


discount_products = Table(
    "discount_products", Base.metadata,
    Column("discount_id", ForeignKey("discounts.id", ondelete="CASCADE"), primary_key=True),
    Column("product_id", ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
)


class Discount(Base):
    __tablename__ = "discounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10))  # fixed | percent
    value: Mapped[Decimal] = mapped_column(Money)
    scope: Mapped[str] = mapped_column(String(15))  # product | subscription
    min_purchase: Mapped[Decimal] = mapped_column(Money, default=0)
    min_quantity: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    usage_limit: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    products: Mapped[list[Product]] = relationship(secondary=discount_products, lazy="selectin")


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str | None] = mapped_column(String(20), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    payment_term_id: Mapped[int | None] = mapped_column(ForeignKey("payment_terms.id"))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("quotation_templates.id"))
    status: Mapped[str] = mapped_column(String(12), default=DRAFT, index=True)
    start_date: Mapped[date] = mapped_column(Date)
    expiry_date: Mapped[date] = mapped_column(Date)
    term_days: Mapped[int] = mapped_column(Integer)  # length of one term, used by renew
    quote_valid_until: Mapped[date | None] = mapped_column(Date)
    # Billing cursor. Period n starts at advance(billing_anchor, n); next_billing_date is that date.
    billing_anchor: Mapped[date] = mapped_column(Date)
    periods_billed: Mapped[int] = mapped_column(Integer, default=0)
    next_billing_date: Mapped[date] = mapped_column(Date)
    paused_on: Mapped[date | None] = mapped_column(Date)
    # Net recurring amount of one billing period (lines + plan fee, before discounts and tax).
    # Kept on the row so recurring-revenue reporting is a single aggregate query.
    recurring_amount: Mapped[Decimal] = mapped_column(Money, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    customer: Mapped[Customer] = relationship(lazy="joined")
    plan: Mapped[Plan] = relationship(lazy="joined")
    payment_term: Mapped[PaymentTerm | None] = relationship(lazy="joined")
    lines: Mapped[list["SubscriptionLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="SubscriptionLine.id")

    __table_args__ = (Index("ix_sub_billing", "status", "next_billing_date"),)


class SubscriptionLine(Base):
    __tablename__ = "subscription_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    tax_id: Mapped[int | None] = mapped_column(ForeignKey("taxes.id"))
    product: Mapped[Product] = relationship(lazy="joined")
    variant: Mapped[ProductVariant | None] = relationship(lazy="joined")
    tax: Mapped[Tax | None] = relationship(lazy="joined")


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str | None] = mapped_column(String(24), unique=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), default=INV_DRAFT)
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    subtotal: Mapped[Decimal] = mapped_column(Money, default=0)  # before discount, before tax
    discount_total: Mapped[Decimal] = mapped_column(Money, default=0)
    tax_total: Mapped[Decimal] = mapped_column(Money, default=0)
    total: Mapped[Decimal] = mapped_column(Money, default=0)
    amount_paid: Mapped[Decimal] = mapped_column(Money, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    customer: Mapped[Customer] = relationship(lazy="joined")
    subscription: Mapped[Subscription] = relationship(lazy="raise")
    lines: Mapped[list["InvoiceLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="InvoiceLine.id")
    payments: Mapped[list["Payment"]] = relationship(
        lazy="selectin", order_by="Payment.id", back_populates="invoice")

    __table_args__ = (
        # "Nothing billed twice": one live invoice per subscription period, enforced by the DB.
        # A cancelled invoice frees its period so it can be billed again.
        Index("uq_invoice_period", "subscription_id", "period_start", unique=True,
              sqlite_where=text("status != 'cancelled'"),
              postgresql_where=text("status != 'cancelled'")),
        Index("ix_invoice_status_due", "status", "due_date"),
    )

    @property
    def balance(self) -> Decimal:
        return self.total - self.amount_paid


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))  # null = plan fee
    discount_id: Mapped[int | None] = mapped_column(ForeignKey("discounts.id"))
    description: Mapped[str] = mapped_column(String(240))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    gross: Mapped[Decimal] = mapped_column(Money)
    discount_amount: Mapped[Decimal] = mapped_column(Money, default=0)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)  # snapshot
    tax_amount: Mapped[Decimal] = mapped_column(Money, default=0)
    total: Mapped[Decimal] = mapped_column(Money)


class InvoiceDiscountUse(Base):
    """Which discounts an invoice consumed, so cancelling the invoice can hand the use back."""
    __tablename__ = "invoice_discount_uses"
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), primary_key=True)
    discount_id: Mapped[int] = mapped_column(ForeignKey("discounts.id"), primary_key=True)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    method: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Money)
    paid_on: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    invoice: Mapped[Invoice] = relationship(back_populates="payments", lazy="raise")
