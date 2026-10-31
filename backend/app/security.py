import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import SECRET_KEY, TOKEN_TTL_MINUTES

ALGO = "HS256"


def validate_password(pw: str) -> str | None:
    """Returns a human message when the password is unacceptable, else None."""
    if len(pw) <= 8:
        return "Password must be more than 8 characters"
    if not re.search(r"[A-Z]", pw):
        return "Password needs an uppercase letter"
    if not re.search(r"[a-z]", pw):
        return "Password needs a lowercase letter"
    if not re.search(r"[^A-Za-z0-9]", pw):
        return "Password needs a special character"
    if len(pw.encode()) > 72:  # bcrypt silently truncates beyond 72 bytes; refuse instead
        return "Password is too long (72 bytes max)"
    return None


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def make_token(user_id: int, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES)
    return jwt.encode({"sub": str(user_id), "role": role, "exp": exp}, SECRET_KEY, algorithm=ALGO)


def read_token(token: str) -> int | None:
    try:
        return int(jwt.decode(token, SECRET_KEY, algorithms=[ALGO])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def new_reset_token() -> tuple[str, str]:
    """(token to email, hash to store). Only the hash is kept, so a DB leak is not a reset leak."""
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
