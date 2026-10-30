"""Slot lifecycle transitions: start, done, not_served (Contract Section 9 & Step 07)."""

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app import clock
from app.errors import VaariError
from app.event_log import log_event
from app.evidence.checks import run_checks
from app.evidence.photos import process_photo
from app.evidence.position import check_position
from app.evidence.record import create_record
from app.models import Evidence, Farmer, Plot, Request, ServiceRecord, Slot
from app.routes.common import get_or_create_home_centre
from app.scheduler.service import run_for_centre


async def start_slot(
    session: Session,
    slot: Slot,
    photo: UploadFile | None = None,
    lat: float | None = None,
    lon: float | None = None,
    accuracy_m: float | None = None,
) -> tuple[Evidence, str]:
    """Transition slot: scheduled -> in_progress."""
    if slot.status == "in_progress":
        raise VaariError(
            error_code="DUPLICATE_START",
            message="Slot is already in progress.",
            http_status=409,
            details={"slot_id": slot.id, "status": slot.status},
        )
    if slot.status != "scheduled":
        raise VaariError(
            error_code="INVALID_TRANSITION",
            message=f"Cannot start slot in status '{slot.status}'.",
            http_status=409,
            details={"slot_id": slot.id, "status": slot.status},
        )

    req = session.query(Request).filter_by(id=slot.request_id).one()
    farmer = session.query(Farmer).filter_by(id=req.farmer_id).one()
    plot = session.query(Plot).filter_by(id=req.plot_id).first()

    if farmer.consent_evidence and photo is None:
        raise VaariError(
            error_code="EVIDENCE_MISSING",
            message="Start photo is required when evidence consent is granted.",
            http_status=422,
            details={"field": "photo"},
        )

    photo_path, photo_sha256, photo_bytes = await process_photo(slot.id, "start", photo)

    server_time = clock.now_utc()
    pos_res = check_position(lat, lon, accuracy_m, plot)
    pos_state = pos_res["position_state"]

    ev = Evidence(
        slot_id=slot.id,
        kind="start",
        server_time=server_time,
        lat=lat,
        lon=lon,
        accuracy_m=accuracy_m,
        distance_to_plot_m=pos_res["distance_to_plot_m"],
        plausible=pos_res["plausible"],
        photo_path=photo_path,
        photo_sha256=photo_sha256,
        photo_bytes=photo_bytes,
    )
    session.add(ev)

    slot.status = "in_progress"
    slot.started_at = server_time
    session.flush()

    log_event(session, actor="driver", entity="slot", entity_id=slot.id, event="started")
    return ev, pos_state


async def done_slot(
    session: Session,
    slot: Slot,
    photo: UploadFile | None = None,
    lat: float | None = None,
    lon: float | None = None,
    accuracy_m: float | None = None,
    service_code: str | None = None,
) -> tuple[Evidence, ServiceRecord, str]:
    """Transition slot: in_progress -> done."""
    if slot.status != "in_progress":
        raise VaariError(
            error_code="INVALID_TRANSITION",
            message=f"Cannot complete slot in status '{slot.status}'. Must be in_progress.",
            http_status=409,
            details={"slot_id": slot.id, "status": slot.status},
        )

    req = session.query(Request).filter_by(id=slot.request_id).one()
    farmer = session.query(Farmer).filter_by(id=req.farmer_id).one()
    plot = session.query(Plot).filter_by(id=req.plot_id).first()

    if farmer.consent_evidence and photo is None:
        raise VaariError(
            error_code="EVIDENCE_MISSING",
            message="Done photo is required when evidence consent is granted.",
            http_status=422,
            details={"field": "photo"},
        )

    photo_path, photo_sha256, photo_bytes = await process_photo(slot.id, "done", photo)

    server_time = clock.now_utc()
    pos_res = check_position(lat, lon, accuracy_m, plot)
    pos_state = pos_res["position_state"]

    ev = Evidence(
        slot_id=slot.id,
        kind="done",
        server_time=server_time,
        lat=lat,
        lon=lon,
        accuracy_m=accuracy_m,
        distance_to_plot_m=pos_res["distance_to_plot_m"],
        plausible=pos_res["plausible"],
        photo_path=photo_path,
        photo_sha256=photo_sha256,
        photo_bytes=photo_bytes,
    )
    session.add(ev)
    session.flush()

    slot.status = "done"
    slot.done_at = server_time
    slot.code_entered = service_code

    flags = run_checks(session, slot)
    slot.flags_json = flags
    slot.needs_review = len(flags) > 0

    session.flush()

    record = create_record(session, slot)

    req.status = "done"
    req.updated_at = server_time

    log_event(session, actor="driver", entity="slot", entity_id=slot.id, event="done")
    log_event(session, actor="system", entity="request", entity_id=req.id, event="done")
    log_event(
        session,
        actor="system",
        entity="service_record",
        entity_id=record.id,
        event="created",
        payload={"token": record.token},
    )

    return ev, record, pos_state


def not_served_slot(
    session: Session,
    slot: Slot,
    reason: str,
    note: str | None = None,
) -> Slot:
    """Transition slot from scheduled or in_progress to not_served; reset request to open."""
    if slot.status not in ("scheduled", "in_progress"):
        raise VaariError(
            error_code="INVALID_TRANSITION",
            message=f"Cannot mark slot not-served from status '{slot.status}'.",
            http_status=409,
            details={"slot_id": slot.id, "status": slot.status},
        )

    slot.status = "not_served"
    slot.not_served_reason = reason
    slot.not_served_note = note

    req = session.query(Request).filter_by(id=slot.request_id).one()
    req.status = "open"
    req.updated_at = clock.now_utc()

    log_event(
        session,
        actor="driver",
        entity="slot",
        entity_id=slot.id,
        event="not_served",
        payload={"reason": reason},
    )

    home_centre = get_or_create_home_centre(session)
    run_for_centre(session, home_centre.id)
    return slot
