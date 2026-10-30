"""Append-only audit event log for Vaari."""

from typing import Any

from sqlalchemy.orm import Session

from app import clock
from app.models import EventLog


def log_event(
    session: Session,
    actor: str,
    entity: str,
    entity_id: int,
    event: str,
    payload: dict[str, Any] | None = None,
) -> EventLog:
    """Insert a new event_log row. Append-only; no update or delete operations exist.

    An ``operator`` actor is labelled with the signed-in account when there is one,
    for example ``operator:asha``.
    """
    if actor == "operator":
        from app.auth import current_principal

        principal = current_principal.get()
        if principal is not None:
            actor = principal.actor
    entry = EventLog(
        actor=actor,
        entity=entity,
        entity_id=entity_id,
        event=event,
        payload_json=payload,
        at=clock.now_utc(),
    )
    session.add(entry)
    return entry
