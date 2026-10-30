"""Sign-in routes for staff accounts (pilot v0.2)."""

from typing import Any

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import clock
from app.auth import Principal, get_principal
from app.db import get_db
from app.errors import VaariError
from app.event_log import log_event
from app.models import UserAccount
from app.passwords import verify_password
from app.ratelimit import lockout, retry_after_seconds
from app.sessions import issue_session, resolve_session, revoke_session

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def normalize_username(username: str) -> str:
    return username.strip().lower()


@router.post("/login")
def login(payload: LoginIn, session: Session = Depends(get_db)) -> dict[str, Any]:
    username = normalize_username(payload.username)
    locked_s = lockout.seconds_locked(username)
    if locked_s > 0:
        # Same answer whether or not the username exists, and even for the right password.
        raise VaariError(
            error_code="RATE_LIMITED",
            message="Too many wrong passwords for this username. Try again later.",
            http_status=429,
            details={"retry_after_s": retry_after_seconds(locked_s)},
        )
    user = session.query(UserAccount).filter_by(username=username).first()
    ok = verify_password(user.password_hash if user else None, payload.password)
    if not ok or user is None or not user.active:
        if lockout.record_failure(username) and user is not None:
            log_event(session, actor="system", entity="user_account", entity_id=user.id, event="login_locked")
            session.commit()
        raise VaariError(
            error_code="UNAUTHORIZED",
            message="Wrong username or password.",
            http_status=401,
        )
    lockout.record_success(username)
    token, expires = issue_session(session, user)
    user.last_login_at = clock.now_utc()
    session.flush()
    log_event(session, actor=f"{user.role}:{user.username}", entity="user_account", entity_id=user.id, event="login")
    session.commit()
    return {
        "token": token,
        "token_type": "bearer",
        "expires_at": clock.iso_z(expires),
        "user": {"username": user.username, "role": user.role},
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    authorization: str | None = Header(None, alias="Authorization"),
    session: Session = Depends(get_db),
):
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    found = resolve_session(session, token)
    if found is not None:
        user, row = found
        revoke_session(session, row)
        log_event(session, actor=f"{user.role}:{user.username}", entity="user_account", entity_id=user.id, event="logout")
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
def me(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return {
        "username": principal.username,
        "roles": sorted(principal.roles),
        "via": principal.via,
    }
