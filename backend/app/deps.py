from datetime import date

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .db import get_db
from .schemas import UserOut
from .security import read_token

bearer = HTTPBearer(auto_error=False)


def today() -> date:
    """The one place 'today' comes from, so tests can pin it."""
    return date.today()


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> m.User:
    uid = read_token(creds.credentials) if creds else None
    user = db.get(m.User, uid) if uid else None
    if not user or not user.is_active:
        raise HTTPException(401, "Please sign in", headers={"WWW-Authenticate": "Bearer"})
    return user


def require(*roles: str):
    def dep(user: m.User = Depends(current_user)) -> m.User:
        if user.role not in roles:
            raise HTTPException(403, "You do not have access to this")
        return user
    return dep


STAFF_UP = require(m.ADMIN, m.STAFF)
ADMIN_ONLY = require(m.ADMIN)


def customer_id_of(db: Session, user: m.User) -> int | None:
    return db.scalar(select(m.Customer.id).where(m.Customer.user_id == user.id))


def user_out(db: Session, user: m.User) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name, role=user.role,
                   is_active=user.is_active, customer_id=customer_id_of(db, user))


def page_args(page: int = 1, page_size: int = 25) -> tuple[int, int]:
    return max(page, 1), min(max(page_size, 1), 200)
