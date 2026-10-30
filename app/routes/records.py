"""API routes for service records and verification (Contract Section 11)."""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import clock
from app.db import get_db
from app.enums import from_x100
from app.errors import VaariError
from app.evidence.record import verify
from app.models import Evidence, Farmer, Machine, Plot, Request, ServiceRecord, Slot
from app.schemas import RecordOut
from app.tokens import require_live_link

router = APIRouter(prefix="/records", tags=["records"])


@router.get("/{token}", response_model=RecordOut)
def get_service_record(
    token: str,
    session: Session = Depends(get_db),
):
    record = session.query(ServiceRecord).filter_by(token=token).first()
    if record is None:
        raise VaariError("NOT_FOUND", "Service record not found.", 404)
    require_live_link(record.token_expires_at, record.token_revoked_at, "record")

    slot = session.query(Slot).filter_by(id=record.slot_id).one()
    req = session.query(Request).filter_by(id=slot.request_id).one()
    farmer = session.query(Farmer).filter_by(id=req.farmer_id).one()
    plot = session.query(Plot).filter_by(id=req.plot_id).one()
    machine = session.query(Machine).filter_by(id=slot.machine_id).one()

    evidence_rows = (
        session.query(Evidence)
        .filter_by(slot_id=slot.id)
        .order_by(Evidence.id.asc())
        .all()
    )
    start_ev = next((e for e in evidence_rows if e.kind == "start"), None)
    done_ev = next((e for e in evidence_rows if e.kind == "done"), None)

    def determine_pos_state(ev: Evidence | None) -> str:
        if ev is None or ev.lat is None or ev.lon is None:
            return "not_given"
        if ev.plausible is True:
            return "plausible"
        if ev.plausible is False:
            return "mismatch"
        return "not_checked"

    start_pos = determine_pos_state(start_ev)
    done_pos = determine_pos_state(done_ev)

    start_photo = "present" if (start_ev and start_ev.photo_path) else "none"
    done_photo = "present" if (done_ev and done_ev.photo_path) else "none"

    evidence_note = None
    if not farmer.consent_evidence:
        evidence_note = "times only: no evidence consent"

    badges = []
    if req.source == "seed":
        badges.append("seeded request")
    if farmer.consent_simulated:
        badges.append("consent simulated")

    if start_pos == "not_given" or done_pos == "not_given":
        badges.append("position self-reported")
    elif start_pos == "not_checked" or done_pos == "not_checked":
        badges.append("position not checked")

    return RecordOut(
        request_id=f"VR-{req.id}",
        village=plot.village_name,
        machine=machine.name,
        acres=from_x100(req.acres_x100),
        service_type=req.service_type,
        scheduled=str(slot.service_date),
        deadline_date=str(req.deadline_date) if req.deadline_date else "",
        started_at=clock.iso_z(slot.started_at) if slot.started_at else None,
        done_at=clock.iso_z(slot.done_at) if slot.done_at else None,
        start_position=start_pos,
        done_position=done_pos,
        start_photo=start_photo,
        done_photo=done_photo,
        evidence_note=evidence_note,
        farmer_confirmed=slot.farmer_confirmed,
        outcome=record.outcome,
        on_time=record.on_time,
        flags=slot.flags_json or [],
        needs_review=slot.needs_review,
        badges=badges,
        record_hash=record.record_hash,
        hash_version=record.hash_version,
    )


@router.get("/{token}/verify")
def verify_service_record(
    token: str,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    record = session.query(ServiceRecord).filter_by(token=token).first()
    if record is None:
        raise VaariError("NOT_FOUND", "Service record not found.", 404)
    require_live_link(record.token_expires_at, record.token_revoked_at, "record")
    return verify(session, token)
