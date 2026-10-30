"""Signed, expiring login sessions (pilot v0.2).

A session token looks like ``v1.<sid>.<expires_unix>.<signature>``. The
signature is HMAC-SHA256 over the first three parts with VAARI_SECRET_KEY.
The database keeps only a SHA-256 of ``sid``, so a copy of the database
cannot be used to sign in. Logging out sets ``revoked_at``.
"""

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import clock
from app.config import settings
from app.models import AuthSession, UserAccount

TOKEN_VERSION = "v1"

# In development without VAARI_SECRET_KEY, sign with a random per-process key.
_dev_secret = secrets.token_bytes(32)


def _secret() -> bytes:
    key = settings.secret_key
    if key:
        return key.encode("utf-8")
    return _dev_secret


def _sign(message: str) -> str:
    mac = hmac.new(_secret(), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def _sid_hash(sid: str) -> str:
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def issue_session(session: Session, user: UserAccount) -> tuple[str, datetime]:
    now = clock.now_utc()
    expires = now + timedelta(hours=settings.session_hours)
    sid = secrets.token_urlsafe(24)
    row = AuthSession(
        sid_sha256=_sid_hash(sid),
        user_id=user.id,
        created_at=now,
        expires_at=expires,
        revoked_at=None,
    )
    session.add(row)
    body = f"{TOKEN_VERSION}.{sid}.{int(expires.timestamp())}"
    return f"{body}.{_sign(body)}", expires


def _parse(token: str) -> tuple[str, int] | None:
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != TOKEN_VERSION:
        return None
    body = ".".join(parts[:3])
    if not hmac.compare_digest(_sign(body), parts[3]):
        return None
    try:
        exp = int(parts[2])
    except ValueError:
        return None
    return parts[1], exp


def resolve_session(session: Session, token: str | None) -> tuple[UserAccount, AuthSession] | None:
    """Return (user, session row) for a valid, unexpired, unrevoked token of an active user."""
    if not token:
        return None
    parsed = _parse(token)
    if parsed is None:
        return None
    sid, exp = parsed
    now = clock.now_utc()
    if exp <= int(now.timestamp()):
        return None
    row = session.query(AuthSession).filter_by(sid_sha256=_sid_hash(sid)).first()
    if row is None or row.revoked_at is not None or _aware(row.expires_at) <= now:
        return None
    user = session.query(UserAccount).filter_by(id=row.user_id).first()
    if user is None or not user.active:
        return None
    return user, row


def revoke_session(session: Session, row: AuthSession) -> None:
    if row.revoked_at is None:
        row.revoked_at = clock.now_utc()


def revoke_all_for_user(session: Session, user_id: int) -> int:
    now = clock.now_utc()
    rows = session.query(AuthSession).filter_by(user_id=user_id, revoked_at=None).all()
    for r in rows:
        r.revoked_at = now
    return len(rows)
