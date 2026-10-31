from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import FRONTEND_URL, RESET_TTL_MINUTES
from ..db import get_db
from ..deps import ADMIN_ONLY, current_user, user_out
from ..schemas import ForgotIn, LoginIn, RegisterIn, ResetIn, TokenOut, UserOut
from ..security import (hash_password, hash_reset_token, make_token, new_reset_token,
                        validate_password, verify_password)
from ..services.mail import send_mail

router = APIRouter(tags=["auth"])


def _check_password(pw: str) -> None:
    problem = validate_password(pw)
    if problem:
        raise HTTPException(422, problem)


@router.post("/auth/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    _check_password(body.password)
    if db.scalar(select(m.User.id).where(m.User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user = m.User(email=email, name=body.name.strip(), password_hash=hash_password(body.password),
                  role=m.CUSTOMER)
    db.add(user)
    db.flush()
    # Staff may already have created this customer (e.g. for a quotation): claim that record
    # rather than creating a second one, so their existing subscriptions show up in the portal.
    existing = db.scalar(select(m.Customer).where(
        func.lower(m.Customer.email) == email, m.Customer.user_id.is_(None)))
    if existing:
        existing.user_id = user.id
    else:
        db.add(m.Customer(user_id=user.id, name=user.name, email=email))
    db.commit()
    return TokenOut(access_token=make_token(user.id, user.role), user=user_out(db, user))


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(m.User).where(m.User.email == body.email.lower()))
    # One message for unknown email, wrong password and disabled account.
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    return TokenOut(access_token=make_token(user.id, user.role), user=user_out(db, user))


@router.get("/auth/me", response_model=UserOut)
def me(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return user_out(db, user)


@router.post("/auth/forgot-password")
def forgot(body: ForgotIn, db: Session = Depends(get_db)):
    user = db.scalar(select(m.User).where(m.User.email == body.email.lower()))
    if user and user.is_active:
        token, digest = new_reset_token()
        db.add(m.PasswordReset(user_id=user.id, token_hash=digest,
                               expires_at=m.utcnow() + timedelta(minutes=RESET_TTL_MINUTES)))
        send_mail(db, user.email, "Reset your Brightloop password",
                  f"Hi {user.name},\n\nUse this link to choose a new password "
                  f"(valid for {RESET_TTL_MINUTES} minutes):\n{FRONTEND_URL}/reset-password?token={token}\n\n"
                  "If you did not ask for this, ignore this email.")
        db.commit()
    # Same answer whether or not the account exists, so the form cannot be used to probe emails.
    return {"message": "If that email is registered, a reset link is on its way."}


@router.post("/auth/reset-password")
def reset(body: ResetIn, db: Session = Depends(get_db)):
    _check_password(body.password)
    row = db.scalar(select(m.PasswordReset).where(m.PasswordReset.token_hash == hash_reset_token(body.token)))
    now = m.utcnow()
    expires = row.expires_at.replace(tzinfo=now.tzinfo) if row and row.expires_at.tzinfo is None else (row.expires_at if row else None)
    if not row or row.used_at or expires < now:
        raise HTTPException(400, "This reset link is invalid or has expired")
    user = db.get(m.User, row.user_id)
    user.password_hash = hash_password(body.password)
    row.used_at = now
    db.commit()
    return {"message": "Password updated. You can sign in now."}


# ---------- staff management (admin only) ----------
@router.post("/users/staff", response_model=UserOut, status_code=201)
def add_staff(body: RegisterIn, _: m.User = Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    email = body.email.lower()
    _check_password(body.password)
    if db.scalar(select(m.User.id).where(m.User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user = m.User(email=email, name=body.name.strip(), password_hash=hash_password(body.password),
                  role=m.STAFF)
    db.add(user)
    db.commit()
    return user_out(db, user)


@router.get("/users", response_model=list[UserOut])
def list_users(_: m.User = Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    users = db.scalars(select(m.User).where(m.User.role != m.CUSTOMER).order_by(m.User.id)).all()
    return [user_out(db, u) for u in users]


@router.patch("/users/{user_id}/active", response_model=UserOut)
def set_active(user_id: int, active: bool, admin: m.User = Depends(ADMIN_ONLY), db: Session = Depends(get_db)):
    user = db.get(m.User, user_id)
    if not user or user.role == m.CUSTOMER:
        raise HTTPException(404, "Staff member not found")
    if user.id == admin.id:
        raise HTTPException(409, "You cannot disable your own account")
    user.is_active = active
    db.commit()
    return user_out(db, user)
