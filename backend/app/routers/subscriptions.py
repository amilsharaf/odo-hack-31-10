from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import models as m
from .. import deps
from ..db import get_db
from ..deps import STAFF_UP, current_user, customer_id_of, page_args
from ..schemas import (CustomerIn, CustomerOut, SubscriptionIn, SubscriptionOut, SubscriptionPatch,
                       SubscriptionRow, TransitionIn)
from ..services import subscriptions as svc

router = APIRouter(tags=["subscriptions"])


# ---------- customers (staff) ----------
@router.get("/customers")
def list_customers(q: str | None = None, page: int = 1, page_size: int = 25,
                   _=Depends(STAFF_UP), db: Session = Depends(get_db)):
    page, page_size = page_args(page, page_size)
    stmt = select(m.Customer)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(m.Customer.name).like(like), func.lower(m.Customer.email).like(like),
                              func.lower(func.coalesce(m.Customer.company, "")).like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(m.Customer.name).limit(page_size).offset((page - 1) * page_size)).all()
    return {"items": [CustomerOut.model_validate(r) for r in rows], "total": total,
            "page": page, "page_size": page_size}


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(body: CustomerIn, _=Depends(STAFF_UP), db: Session = Depends(get_db)):
    c = m.Customer(**body.model_dump())
    c.email = c.email.lower()
    db.add(c)
    db.commit()
    return c


@router.put("/customers/{id:int}", response_model=CustomerOut)
def update_customer(id: int, body: CustomerIn, _=Depends(STAFF_UP), db: Session = Depends(get_db)):
    c = db.get(m.Customer, id)
    if not c:
        raise HTTPException(404, "Customer not found")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    c.email = c.email.lower()
    db.commit()
    return c


@router.get("/customers/me", response_model=CustomerOut)
def my_profile(user=Depends(current_user), db: Session = Depends(get_db)):
    cid = customer_id_of(db, user)
    if not cid:
        raise HTTPException(404, "No customer profile for this account")
    return db.get(m.Customer, cid)


@router.put("/customers/me", response_model=CustomerOut)
def update_my_profile(body: CustomerIn, user=Depends(current_user), db: Session = Depends(get_db)):
    cid = customer_id_of(db, user)
    if not cid:
        raise HTTPException(404, "No customer profile for this account")
    c = db.get(m.Customer, cid)
    # The login email is the account identity; changing it is deliberately not offered here.
    c.name, c.company, c.phone, c.address = body.name, body.company, body.phone, body.address
    db.commit()
    return c


# ---------- subscriptions ----------
def _load(db: Session, id_: int, user: m.User) -> m.Subscription:
    sub = db.get(m.Subscription, id_)
    # A customer asking for someone else's subscription gets the same 404 as a missing one.
    if not sub or (user.role == m.CUSTOMER and sub.customer_id != customer_id_of(db, user)):
        raise HTTPException(404, "Subscription not found")
    return sub


@router.get("/subscriptions")
def list_subscriptions(status: str | None = None, customer_id: int | None = None, plan_id: int | None = None,
                       q: str | None = None, page: int = 1, page_size: int = 25,
                       user=Depends(current_user), db: Session = Depends(get_db)):
    page, page_size = page_args(page, page_size)
    S, C, P = m.Subscription, m.Customer, m.Plan
    stmt = (select(S.id, S.number, S.status, S.customer_id, C.name.label("customer_name"),
                   P.name.label("plan_name"), P.interval.label("plan_interval"), S.start_date,
                   S.expiry_date, S.next_billing_date, S.recurring_amount)
            .join(C, C.id == S.customer_id).join(P, P.id == S.plan_id))
    if user.role == m.CUSTOMER:
        stmt = stmt.where(S.customer_id == customer_id_of(db, user))
    elif customer_id:
        stmt = stmt.where(S.customer_id == customer_id)
    if status:
        stmt = stmt.where(S.status == status)
    if plan_id:
        stmt = stmt.where(S.plan_id == plan_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(S.number).like(like), func.lower(C.name).like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(S.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    return {"items": [SubscriptionRow(**r._mapping) for r in rows], "total": total,
            "page": page, "page_size": page_size}


def _out(sub: m.Subscription, user: m.User) -> SubscriptionOut:
    return svc.to_out(sub, user.role, deps.today())


def _domain(fn):
    """Turn rule violations into clean HTTP errors."""
    try:
        return fn()
    except svc.DomainError as e:
        raise HTTPException(e.status, e.message)


@router.post("/subscriptions", response_model=SubscriptionOut, status_code=201)
def create_subscription(body: SubscriptionIn, user=Depends(current_user), db: Session = Depends(get_db)):
    if user.role == m.CUSTOMER:
        customer_id = customer_id_of(db, user)
    else:
        customer_id = body.customer_id
        if not customer_id or not db.get(m.Customer, customer_id):
            raise HTTPException(422, "Choose a customer")
    sub = _domain(lambda: svc.create(db, user=user, customer_id=customer_id, data=body, today=deps.today()))
    db.commit()
    db.refresh(sub)
    return _out(sub, user)


@router.get("/subscriptions/{id}", response_model=SubscriptionOut)
def get_subscription(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    return _out(_load(db, id, user), user)


@router.patch("/subscriptions/{id}", response_model=SubscriptionOut)
def patch_subscription(id: int, body: SubscriptionPatch, user=Depends(current_user), db: Session = Depends(get_db)):
    sub = _load(db, id, user)
    _domain(lambda: svc.update(db, sub, body, user, deps.today()))
    db.commit()
    db.refresh(sub)
    return _out(sub, user)


@router.post("/subscriptions/{id}/transition", response_model=SubscriptionOut)
def transition(id: int, body: TransitionIn, user=Depends(current_user), db: Session = Depends(get_db)):
    sub = db.get(m.Subscription, id, with_for_update=True)
    if not sub or (user.role == m.CUSTOMER and sub.customer_id != customer_id_of(db, user)):
        raise HTTPException(404, "Subscription not found")
    _domain(lambda: svc.transition(sub, body.action, user.role, deps.today()))
    db.commit()
    db.refresh(sub)
    return _out(sub, user)
