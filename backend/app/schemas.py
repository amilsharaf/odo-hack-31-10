from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

Interval = Literal["daily", "weekly", "monthly", "yearly"]
Method = Literal["card", "bank_transfer", "cash", "upi", "cheque"]


def money(**kw):
    return Field(max_digits=12, decimal_places=2, **kw)


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    customer_id: int | None = None


class TokenOut(BaseModel):
    access_token: str
    user: UserOut


# ---------- catalog ----------
class TaxIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    active: bool = True


class TaxOut(ORM, TaxIn):
    id: int


class TermIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    days: int = Field(ge=0, le=365)


class TermOut(ORM, TermIn):
    id: int


class VariantIn(BaseModel):
    attribute: str = Field(min_length=1, max_length=60)
    value: str = Field(min_length=1, max_length=60)
    extra_price: Decimal = money(default=Decimal(0))


class VariantOut(ORM, VariantIn):
    id: int


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(default="service", max_length=30)
    sales_price: Decimal = money(ge=0)
    cost_price: Decimal = money(default=Decimal(0), ge=0)
    notes: str | None = None
    tax_id: int | None = None
    active: bool = True
    variants: list[VariantIn] = []


class ProductOut(ORM):
    id: int
    name: str
    type: str
    sales_price: Decimal
    cost_price: Decimal
    notes: str | None
    tax_id: int | None
    active: bool
    tax: TaxOut | None
    variants: list[VariantOut]


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price: Decimal = money(ge=0)
    interval: Interval
    min_quantity: int = Field(default=1, ge=1)
    valid_from: date | None = None
    valid_to: date | None = None
    tax_id: int | None = None
    auto_close: bool = False
    closable: bool = True
    pausable: bool = False
    renewable: bool = True
    active: bool = True

    @model_validator(mode="after")
    def _dates(self):
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("Availability end must not be before its start")
        return self


class PlanOut(ORM, PlanIn):
    id: int
    tax: TaxOut | None = None


class TemplateLineIn(BaseModel):
    product_id: int
    variant_id: int | None = None
    quantity: int = Field(default=1, ge=1)


class TemplateLineOut(ORM, TemplateLineIn):
    id: int


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    validity_days: int = Field(default=30, ge=1, le=365)
    plan_id: int
    notes: str | None = None
    lines: list[TemplateLineIn] = []


class TemplateOut(ORM):
    id: int
    name: str
    validity_days: int
    plan_id: int
    notes: str | None
    plan: PlanOut
    lines: list[TemplateLineOut]


class DiscountIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["fixed", "percent"]
    value: Decimal = money(gt=0)
    scope: Literal["product", "subscription"]
    product_ids: list[int] = []
    min_purchase: Decimal = money(default=Decimal(0), ge=0)
    min_quantity: int = Field(default=0, ge=0)
    start_date: date | None = None
    end_date: date | None = None
    usage_limit: int | None = Field(default=None, ge=1)
    active: bool = True

    @model_validator(mode="after")
    def _check(self):
        if self.kind == "percent" and self.value > 100:
            raise ValueError("A percentage discount cannot exceed 100")
        if self.scope == "product" and not self.product_ids:
            raise ValueError("Pick at least one product for a product discount")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("Discount end date must not be before its start")
        return self


class DiscountOut(DiscountIn):
    id: int
    used_count: int


# ---------- customers ----------
class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    company: str | None = None
    phone: str | None = None
    address: str | None = None


class CustomerOut(ORM, CustomerIn):
    id: int
    user_id: int | None


# ---------- subscriptions ----------
class SubLineIn(BaseModel):
    product_id: int
    variant_id: int | None = None
    quantity: int = Field(ge=1)
    unit_price: Decimal | None = money(default=None, ge=0)  # staff may negotiate; customers cannot


class SubscriptionIn(BaseModel):
    customer_id: int | None = None  # ignored for customers: they can only create for themselves
    plan_id: int | None = None      # defaults from the template
    template_id: int | None = None
    payment_term_id: int | None = None
    start_date: date | None = None
    expiry_date: date | None = None
    lines: list[SubLineIn] | None = None  # defaults from the template
    notes: str | None = None


class SubscriptionPatch(BaseModel):
    plan_id: int | None = None
    payment_term_id: int | None = None
    start_date: date | None = None
    expiry_date: date | None = None
    lines: list[SubLineIn] | None = None
    notes: str | None = None


class TransitionIn(BaseModel):
    action: Literal["send_quote", "confirm", "activate", "pause", "resume", "close", "renew"]


class SubLineOut(BaseModel):
    id: int
    product_id: int
    product_name: str
    variant_id: int | None
    variant: str | None
    quantity: int
    unit_price: Decimal
    tax_id: int | None
    tax_name: str | None
    tax_rate: Decimal
    net: Decimal
    tax: Decimal
    amount: Decimal


class SubscriptionOut(BaseModel):
    id: int
    number: str | None
    status: str
    customer_id: int
    customer_name: str
    plan_id: int
    plan_name: str
    plan_interval: str
    plan_price: Decimal
    payment_term_id: int | None
    payment_term: str | None
    template_id: int | None
    start_date: date
    expiry_date: date
    quote_valid_until: date | None
    next_billing_date: date
    recurring_amount: Decimal
    notes: str | None
    lines: list[SubLineOut]
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    allowed_actions: list[str]
    created_at: datetime


class SubscriptionRow(BaseModel):
    id: int
    number: str | None
    status: str
    customer_id: int
    customer_name: str
    plan_name: str
    plan_interval: str
    start_date: date
    expiry_date: date
    next_billing_date: date
    recurring_amount: Decimal


# ---------- invoices & payments ----------
class InvoiceLineOut(ORM):
    id: int
    description: str
    quantity: int
    unit_price: Decimal
    gross: Decimal
    discount_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    total: Decimal


class PaymentOut(ORM):
    id: int
    invoice_id: int
    method: str
    amount: Decimal
    paid_on: date
    note: str | None
    created_at: datetime


class InvoiceRow(BaseModel):
    id: int
    number: str | None
    status: str
    display_status: str  # adds "overdue" on top of the stored status
    subscription_id: int
    subscription_number: str | None
    customer_id: int
    customer_name: str
    issue_date: date
    due_date: date
    period_start: date
    period_end: date
    total: Decimal
    amount_paid: Decimal
    balance: Decimal
    days_overdue: int


class InvoiceOut(InvoiceRow):
    customer_email: str
    customer_address: str | None
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    sent_at: datetime | None
    lines: list[InvoiceLineOut]
    payments: list[PaymentOut]


class PaymentIn(BaseModel):
    method: Method
    amount: Decimal = money(gt=0)
    paid_on: date | None = None
    note: str | None = Field(default=None, max_length=500)


class BillingRunIn(BaseModel):
    as_of: date | None = None
    auto_confirm: bool = False
