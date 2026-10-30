"""Driver API routes (Contract Section 11)."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import clock
from app.db import get_db
from app.errors import VaariError
from app.models import Machine, Slot
from app.routes.common import serialize_slot
from app.tokens import require_live_link

router = APIRouter(prefix="/driver", tags=["driver"])


@router.get("/{machine_token}")
def get_driver_view(
    machine_token: str,
    date: date | None = Query(None),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    machine = session.query(Machine).filter_by(link_token=machine_token).first()
    if machine is None:
        raise VaariError("NOT_FOUND", "Machine not found.", 404)
    require_live_link(machine.link_expires_at, machine.link_revoked_at, "driver")

    target_date = date if date is not None else clock.today()

    slots = (
        session.query(Slot)
        .filter_by(machine_id=machine.id, service_date=target_date)
        .filter(Slot.status.in_(["scheduled", "in_progress", "done"]))
        .order_by(Slot.seq.asc())
        .all()
    )

    return {
        "machine": {"id": machine.id, "name": machine.name},
        "date": str(target_date),
        "slots": [serialize_slot(session, s, include_link_token=True) for s in slots],
    }
