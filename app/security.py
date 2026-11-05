
import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .model_db import LoginSession, User, now_utc

SESSION_DAYS = 7
COOKIE_NAME = "task_session"
password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_login_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=now_utc() + timedelta(days=SESSION_DAYS),
    ))
    db.commit()
    return token


def revoke_login_session(db: Session, token: str | None) -> None:
    if not token:
        return
    login_session = db.scalar(select(LoginSession).where(LoginSession.token_hash == hash_token(token)))
    if login_session:
        db.delete(login_session)
        db.commit()