"""Authentication and role checks for Vaari.

Two ways to act as staff:

- **Accounts** (pilot v0.2): ``Authorization: Bearer <session token>`` from
  ``POST /api/auth/login``. Each account has one role, ``operator`` or
  ``officer``. This is the only way in production.
- **Shared demo passcode**: ``X-Vaari-Passcode``. Development mode only. It
  acts with both roles so the demo screens keep working.

Drivers act on one slot with ``X-Vaari-Slot-Token`` (see ``verify_slot_auth``).
All secret comparisons use ``hmac.compare_digest``.
"""

import contextvars
import hmac
from dataclasses import dataclass, field

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import VaariError
from app.models import Slot

ROLE_OPERATOR = "operator"
ROLE_OFFICER = "officer"
ROLES = (ROLE_OPERATOR, ROLE_OFFICER)


@dataclass(frozen=True)
class Principal:
    actor: str  # for event_log: "operator", "operator:asha", "officer:ravi"
    roles: frozenset[str] = field(default_factory=frozenset)
    user_id: int | None = None
    username: str | None = None
    via: str = "passcode"  # passcode | session


# The principal of the current request, used to label event_log rows.
current_principal: contextvars.ContextVar[Principal | None] = contextvars.ContextVar(
    "vaari_current_principal", default=None
)


def secrets_equal(a: str | None, b: str | None) -> bool:
    """Constant-time string comparison. Empty or missing values never match."""
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def passcode_ok(value: str | None) -> bool:
    """True only in development mode and only for the configured passcode."""
    if settings.is_production:
        return False
    return secrets_equal(value, settings.demo_passcode)


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def resolve_principal(
    session: Session,
    authorization: str | None,
    x_vaari_passcode: str | None,
) -> Principal | None:
    from app.sessions import resolve_session

    token = _bearer(authorization)
    if token:
        found = resolve_session(session, token)
        if found is None:
            return None
        user, _row = found
        return Principal(
            actor=f"{user.role}:{user.username}",
            roles=frozenset({user.role}),
            user_id=user.id,
            username=user.username,
            via="session",
        )
    if passcode_ok(x_vaari_passcode):
        return Principal(actor="operator", roles=frozenset(ROLES), via="passcode")
    return None


async def get_principal(
    authorization: str | None = Header(None, alias="Authorization"),
    x_vaari_passcode: str | None = Header(None, alias="X-Vaari-Passcode"),
    session: Session = Depends(get_db),
) -> Principal:
    principal = resolve_principal(session, authorization, x_vaari_passcode)
    if principal is None:
        raise VaariError(
            error_code="UNAUTHORIZED",
            message="Sign in first." if settings.is_production else "Invalid or missing passcode.",
            http_status=401,
        )
    # Set in the request's own task so event_log rows can name the account.
    current_principal.set(principal)
    return principal


async def get_optional_principal(
    authorization: str | None = Header(None, alias="Authorization"),
    x_vaari_passcode: str | None = Header(None, alias="X-Vaari-Passcode"),
    session: Session = Depends(get_db),
) -> Principal | None:
    """Like get_principal, but returns None instead of raising (routes that also accept driver tokens)."""
    principal = resolve_principal(session, authorization, x_vaari_passcode)
    if principal is not None:
        current_principal.set(principal)
    return principal


def require_roles(*allowed: str):
    allowed_set = frozenset(allowed)

    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not (principal.roles & allowed_set):
            raise VaariError(
                error_code="FORBIDDEN",
                message="Your account cannot do this.",
                http_status=403,
                details={"required_roles": sorted(allowed_set)},
            )
        return principal

    return dependency


# Operator-only routes: anything that shows phone numbers, driver links, or changes data.
require_operator = require_roles(ROLE_OPERATOR)
# Read-only oversight routes: no phone numbers and no driver links.
require_staff = require_roles(ROLE_OPERATOR, ROLE_OFFICER)

# Kept for older imports: the passcode dependency is now "operator".
require_passcode = require_operator


async def require_machine_token(
    x_vaari_machine_token: str | None = Header(None, alias="X-Vaari-Machine-Token"),
) -> str:
    if not x_vaari_machine_token:
        raise VaariError(
            error_code="UNAUTHORIZED",
            message="Missing machine token.",
            http_status=401,
        )
    return x_vaari_machine_token


def require_some_slot_credential(
    x_vaari_slot_token: str | None,
    x_vaari_passcode: str | None,
    principal: Principal | None,
) -> None:
    """401 before any lookup when the caller brought no credential at all."""
    if principal is not None and ROLE_OPERATOR in principal.roles:
        return
    if passcode_ok(x_vaari_passcode) or x_vaari_slot_token:
        return
    raise VaariError(
        error_code="UNAUTHORIZED",
        message="Slot token or operator sign-in required.",
        http_status=401,
    )


async def get_slot_caller(
    x_vaari_slot_token: str | None = Header(None, alias="X-Vaari-Slot-Token"),
    x_vaari_passcode: str | None = Header(None, alias="X-Vaari-Passcode"),
    principal: Principal | None = Depends(get_optional_principal),
) -> Principal | None:
    """Dependency for slot actions: 401 early (before body checks) when no credential came."""
    require_some_slot_credential(x_vaari_slot_token, x_vaari_passcode, principal)
    return principal


def verify_slot_auth(
    slot: Slot,
    x_vaari_slot_token: str | None = None,
    x_vaari_passcode: str | None = None,
    principal: Principal | None = None,
) -> str:
    """Verify auth for a specific slot: an operator, or the slot's own token."""
    if principal is not None and ROLE_OPERATOR in principal.roles:
        current_principal.set(principal)
        return "operator"
    if passcode_ok(x_vaari_passcode):
        return "operator"
    if x_vaari_slot_token is not None:
        if secrets_equal(x_vaari_slot_token, slot.link_token):
            return "driver"
        raise VaariError(
            error_code="WRONG_SLOT",
            message="The link token does not belong to this slot.",
            http_status=403,
            details={"slot_id": slot.id},
        )
    raise VaariError(
        error_code="UNAUTHORIZED",
        message="Slot token or operator sign-in required.",
        http_status=401,
    )
