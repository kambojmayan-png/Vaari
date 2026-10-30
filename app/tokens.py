"""Token and service-code generators for Vaari."""

import secrets


def new_token() -> str:
    """Generate a 128-bit URL-safe token (16 bytes)."""
    return secrets.token_urlsafe(16)


def new_service_code() -> str:
    """Generate a 4-digit numeric code as a string (e.g. '0482')."""
    return f"{secrets.randbelow(10000):04d}"


# --- Link expiry and revocation (pilot v0.2) ---

from datetime import datetime, timedelta, timezone  # noqa: E402


def driver_link_expiry() -> datetime:
    from app import clock
    from app.config import settings

    return clock.now_utc() + timedelta(days=settings.driver_link_days)


def record_link_expiry() -> datetime:
    from app import clock
    from app.config import settings

    return clock.now_utc() + timedelta(days=settings.record_link_days)


def link_state(expires_at: datetime | None, revoked_at: datetime | None) -> str:
    """'active', 'expired' or 'revoked'. A missing expiry means the link does not expire."""
    from app import clock

    if revoked_at is not None:
        return "revoked"
    if expires_at is not None:
        exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        if exp <= clock.now_utc():
            return "expired"
    return "active"


def require_live_link(expires_at: datetime | None, revoked_at: datetime | None, what: str) -> None:
    """Raise 410 LINK_EXPIRED when a driver or record link has expired or been turned off."""
    from app.errors import VaariError

    state = link_state(expires_at, revoked_at)
    if state == "active":
        return
    raise VaariError(
        error_code="LINK_EXPIRED",
        message=f"This {what} link has {'been turned off' if state == 'revoked' else 'expired'}. Ask the centre for a new link.",
        http_status=410,
        details={"reason": state},
    )
