"""Products, plans, taxes, payment terms, quotation templates and discounts.

Anyone signed in can read what they need to browse and subscribe (customers only see what is
active); only the admin can change any of it.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from ..db import get_db
from ..deps import ADMIN_ONLY, current_user
from ..schemas import (DiscountIn, DiscountOut, PlanIn, PlanOut, ProductIn, ProductOut, TaxIn, TaxOut,
                       TemplateIn, TemplateOut, TermIn, TermOut)

router = APIRouter(tags=["catalog"])


def _get(db: Session, model, id_: int, what: str):
    row = db.get(model, id_)
    if not row:
        raise HTTPException(404, f"{what} not found")
    return row


def _require_tax(db: Session, tax_id: int | None) -> None:
    if tax_id is not None and not db.get(m.Tax, tax_id):
        raise HTTPException(422, "Tax not found")


def _commit(db: Session, conflict_msg: str):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, conflict_msg)


# ---------- taxes ----------
@router.get("/taxes", response_model=list[TaxOut])
def list_taxes(_=Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(m.Tax).order_by(m.Tax.id)).all()


@router.post("/taxes", response_model=TaxOut, status_code=201)
def create_tax(body: TaxIn, _=Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    t = m.Tax(**body.model_dump())
    db.add(t)
    db.commit()
    return t


@router.put("/taxes/{id}", response_model=TaxOut)
def update_tax(id: int, body: TaxIn, _=Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    t = _get(db, m.Tax, id, "Tax")
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    return t


# ---------- payment terms ----------
@router.get("/payment-terms", response_model=list[TermOut])
def list_terms(_=Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(m.PaymentTerm).order_by(m.PaymentTerm.days)).all()


@router.post("/payment-terms", response_model=TermOut, status_code=201)
def create_term(body: TermIn, _=Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    t = m.PaymentTerm(**body.model_dump())
    db.add(t)
    db.commit()
    return t


@router.delete("/payment-terms/{id}", status_code=204)
def delete_term(id: int, _=Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    db.delete(_get(db, m.PaymentTerm, id, "Payment term"))
    _commit(db, "This payment term is used by a subscription")


# ---------- products ----------
def _apply_product(db: Session, p: m.Product, body: ProductIn) -> None:
    _require_tax(db, body.tax_id)
    for k in ("name", "type", "sales_price", "cost_price", "notes", "tax_id", "active"):
        setattr(p, k, getattr(body, k))
    # Variants are matched on (attribute, value) so existing subscription lines keep pointing at
    # the same row when the admin edits a price.
    keep = {(v.attribute.strip().lower(), v.value.strip().lower()): v for v in body.variants}
    if len(keep) != len(body.variants):
        raise HTTPException(422, "Variant values must be unique within a product")
    for existing in list(p.variants):
        key = (existing.attribute.strip().lower(), existing.value.strip().lower())
        if key in keep:
            existing.extra_price = keep.pop(key).extra_price
        else:
            p.variants.remove(existing)
    for v in keep.values():
        p.variants.append(m.ProductVariant(**v.model_dump()))


@router.get("/products", response_model=list[ProductOut])
def list_products(include_inactive: bool = False, user=Depends(current_user), db: Session = Depends(get_db)):
    q = select(m.Product).order_by(m.Product.name)
    if user.role == m.CUSTOMER or not include_inactive:
        q = q.where(m.Product.active.is_(True))
    return db.scalars(q).unique().all()


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(body: ProductIn, _=Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    p = m.Product()
    _apply_product(db, p, body)
    db.add(p)
    db.commit()
    return p


@router.put("/products/{id}", response_model=ProductOut)
def update_product(id: int, body: ProductIn, _=Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    p = _get(db, m.Product, id, "Product")
    _apply_product(db, p, body)
    _commit(db, "A removed variant is still used by a subscription")
    return p


# ---------- plans ----------
@router.get("/plans", response_model=list[PlanOut])
def list_plans(include_inactive: bool = False, user=Depends(current_user), db: Session = Depends(get_db)):
    q = select(m.Plan).order_by(m.Plan.name)
    if user.role == m.CUSTOMER or not include_inactive:
        q = q.where(m.Plan.active.is_(True))
    return db.scalars(q).unique().all()


@router.post("/plans", response_model=PlanOut, status_code=201)
def create_plan(body: PlanIn, _=Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    _require_tax(db, body.tax_id)
    p = m.Plan(**body.model_dump())
    db.add(p)
    db.commit()
    return p


@router.put("/plans/{id}", response_model=PlanOut)
def update_plan(id: int, body: PlanIn, _=Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    _require_tax(db, body.tax_id)
    p = _get(db, m.Plan, id, "Plan")
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return p


# ---------- quotation templates ----------
def _apply_template(db: Session, t: m.QuotationTemplate, body: TemplateIn) -> None:
    plan = _get(db, m.Plan, body.plan_id, "Plan")
    t.name, t.validity_days, t.notes, t.plan = body.name, body.validity_days, body.notes, plan
    lines = []
    for l in body.lines:
        product = _get(db, m.Product, l.product_id, "Product")
        if l.variant_id is not None and not any(v.id == l.variant_id for v in product.variants):
            raise HTTPException(422, f"Variant {l.variant_id} does not belong to {product.name}")
        lines.append(m.TemplateLine(**l.model_dump()))
    t.lines = lines


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(user=Depends(current_user), db: Session = Depends(get_db)):
    if user.role == m.CUSTOMER:
        raise HTTPException(403, "You do not have access to this")
    return db.scalars(select(m.QuotationTemplate).order_by(m.QuotationTemplate.name)).unique().all()


@router.post("/templates", response_model=TemplateOut, status_code=201)
def create_template(body: TemplateIn, _=Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    t = m.QuotationTemplate()
    _apply_template(db, t, body)
    db.add(t)
    db.commit()
    return t


@router.put("/templates/{id}", response_model=TemplateOut)
def update_template(id: int, body: TemplateIn, _=Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    t = _get(db, m.QuotationTemplate, id, "Template")
    _apply_template(db, t, body)
    db.commit()
    return t


@router.delete("/templates/{id}", status_code=204)
def delete_template(id: int, _=Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    db.delete(_get(db, m.QuotationTemplate, id, "Template"))
    _commit(db, "This template is used by a subscription")


# ---------- discounts ----------
def _discount_out(d: m.Discount) -> DiscountOut:
    return DiscountOut(
        id=d.id, name=d.name, kind=d.kind, value=d.value, scope=d.scope,
        product_ids=[p.id for p in d.products], min_purchase=d.min_purchase,
        min_quantity=d.min_quantity, start_date=d.start_date, end_date=d.end_date,
        usage_limit=d.usage_limit, used_count=d.used_count, active=d.active)


def _apply_discount(db: Session, d: m.Discount, body: DiscountIn) -> None:
    if body.usage_limit is not None and d.used_count > body.usage_limit:
        raise HTTPException(422, f"Already used {d.used_count} times; the limit cannot be lower")
    products = []
    if body.scope == "product":
        products = list(db.scalars(select(m.Product).where(m.Product.id.in_(body.product_ids))))
        if len(products) != len(set(body.product_ids)):
            raise HTTPException(422, "One or more products were not found")
    d.name, d.kind, d.value, d.scope = body.name, body.kind, body.value, body.scope
    d.min_purchase, d.min_quantity = body.min_purchase, body.min_quantity
    d.start_date, d.end_date, d.usage_limit, d.active = body.start_date, body.end_date, body.usage_limit, body.active
    d.products = products


@router.get("/discounts", response_model=list[DiscountOut])
def list_discounts(user=Depends(current_user), db: Session = Depends(get_db)):
    if user.role == m.CUSTOMER:
        raise HTTPException(403, "You do not have access to this")
    return [_discount_out(d) for d in db.scalars(select(m.Discount).order_by(m.Discount.id.desc())).unique()]


@router.post("/discounts", response_model=DiscountOut, status_code=201)
def create_discount(body: DiscountIn, _=Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    d = m.Discount(used_count=0)
    _apply_discount(db, d, body)
    db.add(d)
    db.commit()
    return _discount_out(d)


@router.put("/discounts/{id}", response_model=DiscountOut)
def update_discount(id: int, body: DiscountIn, _=Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    d = _get(db, m.Discount, id, "Discount")
    _apply_discount(db, d, body)
    db.commit()
    return _discount_out(d)
