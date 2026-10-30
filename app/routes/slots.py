"""API routes for slot lifecycle, evidence capture and messaging (Contract Section 11)."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app import clock
from app.auth import (
    ROLE_OPERATOR,
    Principal,
    get_optional_principal,
    get_slot_caller,
    require_operator,
    verify_slot_auth,
)
from app.config import settings
from app.db import get_db
from app.errors import VaariError
from app.evidence.lifecycle import done_slot, not_served_slot, start_slot
from app.messaging.render import render_slot_message
from app.models import Centre, Farmer, Machine, MessageLog, Plot, Request, Slot
from app.routes.common import serialize_slot
from app.schemas import EvidenceDetail, MessageOpenedIn, NotServedIn, SlotEvidenceOut, SlotOut
from app.tokens import require_live_link

router = APIRouter(prefix="/slots", tags=["slots"])


def _check_slot_caller(session, slot, slot_token, passcode, principal) -> str:
    """Operator, or the slot's own token while its machine's driver link is still live."""
    who = verify_slot_auth(slot, slot_token, passcode, principal)
    if who == "driver":
        machine = session.query(Machine).filter_by(id=slot.machine_id).first()
        if machine is not None:
            require_live_link(machine.link_expires_at, machine.link_revoked_at, "driver")
    return who


@router.get("", response_model=list[SlotOut])
def list_slots(
    date: date | None = Query(None),
    machine_id: int | None = Query(None),
    x_vaari_machine_token: str | None = Header(None, alias="X-Vaari-Machine-Token"),
    principal: Principal | None = Depends(get_optional_principal),
    session: Session = Depends(get_db),
):
    # Auth: an operator, or a machine token (driver for that machine)
    machine_for_token = None
    if principal is not None and ROLE_OPERATOR in principal.roles:
        pass
    elif x_vaari_machine_token:
        machine_for_token = (
            session.query(Machine).filter_by(link_token=x_vaari_machine_token).first()
        )
        if not machine_for_token:
            raise VaariError("UNAUTHORIZED", "Invalid machine token.", 401)
        require_live_link(machine_for_token.link_expires_at, machine_for_token.link_revoked_at, "driver")
    else:
        raise VaariError("UNAUTHORIZED", "Operator sign-in or machine token required.", 401)

    query = session.query(Slot)
    if machine_for_token:
        query = query.filter(Slot.machine_id == machine_for_token.id)
    elif machine_id:
        query = query.filter(Slot.machine_id == machine_id)

    if date:
        query = query.filter(Slot.service_date == date)

    slots = query.order_by(Slot.service_date.asc(), Slot.seq.asc()).all()
    return [serialize_slot(session, s, include_link_token=True) for s in slots]


@router.get("/{id}/message")
def get_slot_message(
    id: int,
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
) -> dict[str, Any]:
    slot = session.query(Slot).filter_by(id=id).first()
    if slot is None:
        raise VaariError("NOT_FOUND", "Slot not found.", 404)

    req = session.query(Request).filter_by(id=slot.request_id).one()
    farmer = session.query(Farmer).filter_by(id=req.farmer_id).one()
    plot = session.query(Plot).filter_by(id=req.plot_id).one()
    machine = session.query(Machine).filter_by(id=slot.machine_id).one()
    centre = session.query(Centre).filter_by(id=machine.centre_id).one()

    rendered = render_slot_message(
        slot=slot,
        req=req,
        farmer=farmer,
        plot=plot,
        machine=machine,
        centre=centre,
    )

    # Log message rendered
    mlog = MessageLog(
        slot_id=slot.id,
        farmer_id=farmer.id,
        channel="screen",
        template="v1",
        body=rendered["body"],
        status="rendered",
        created_at=clock.now_utc(),
    )
    session.add(mlog)
    session.commit()

    return rendered


@router.post("/{id}/message/opened", status_code=status.HTTP_204_NO_CONTENT)
def message_opened(
    id: int,
    payload: MessageOpenedIn,
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
):
    slot = session.query(Slot).filter_by(id=id).first()
    if slot is None:
        raise VaariError("NOT_FOUND", "Slot not found.", 404)

    req = session.query(Request).filter_by(id=slot.request_id).one()
    farmer = session.query(Farmer).filter_by(id=req.farmer_id).one()
    plot = session.query(Plot).filter_by(id=req.plot_id).one()
    machine = session.query(Machine).filter_by(id=slot.machine_id).one()
    centre = session.query(Centre).filter_by(id=machine.centre_id).one()

    rendered = render_slot_message(
        slot=slot,
        req=req,
        farmer=farmer,
        plot=plot,
        machine=machine,
        centre=centre,
    )

    now = clock.now_utc()
    slot.notified_at = now

    mlog = MessageLog(
        slot_id=slot.id,
        farmer_id=farmer.id,
        channel=payload.channel,
        template="v1",
        body=rendered["body"],
        status="opened",
        created_at=now,
    )
    session.add(mlog)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{id}/start", response_model=SlotEvidenceOut)
async def start_slot_endpoint(
    id: int,
    photo: UploadFile | None = File(None),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    accuracy_m: float | None = Form(None),
    x_vaari_slot_token: str | None = Header(None, alias="X-Vaari-Slot-Token"),
    x_vaari_passcode: str | None = Header(None, alias="X-Vaari-Passcode"),
    principal: Principal | None = Depends(get_slot_caller),
    session: Session = Depends(get_db),
):
    slot = session.query(Slot).filter_by(id=id).first()
    if slot is None:
        raise VaariError("NOT_FOUND", "Slot not found.", 404)

    # 1. Auth check
    _check_slot_caller(session, slot, x_vaari_slot_token, x_vaari_passcode, principal)

    # 2. Lifecycle start
    ev, pos_state = await start_slot(
        session=session,
        slot=slot,
        photo=photo,
        lat=lat,
        lon=lon,
        accuracy_m=accuracy_m,
    )
    session.commit()

    return SlotEvidenceOut(
        slot_id=slot.id,
        status=slot.status,
        evidence=EvidenceDetail(
            kind=ev.kind,
            lat=ev.lat,
            lon=ev.lon,
            accuracy_m=ev.accuracy_m,
            distance_to_plot_m=ev.distance_to_plot_m,
            plausible=ev.plausible,
            position_state=pos_state,
            photo="present" if ev.photo_path else "none",
            timestamp=clock.iso_z(ev.server_time),
        ),
        flags=slot.flags_json or [],
        needs_review=slot.needs_review,
        record_url=None,
    )


@router.post("/{id}/done", response_model=SlotEvidenceOut)
async def done_slot_endpoint(
    id: int,
    photo: UploadFile | None = File(None),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    accuracy_m: float | None = Form(None),
    service_code: str | None = Form(None),
    x_vaari_slot_token: str | None = Header(None, alias="X-Vaari-Slot-Token"),
    x_vaari_passcode: str | None = Header(None, alias="X-Vaari-Passcode"),
    principal: Principal | None = Depends(get_slot_caller),
    session: Session = Depends(get_db),
):
    slot = session.query(Slot).filter_by(id=id).first()
    if slot is None:
        raise VaariError("NOT_FOUND", "Slot not found.", 404)

    # 1. Auth check
    _check_slot_caller(session, slot, x_vaari_slot_token, x_vaari_passcode, principal)

    # 2. Lifecycle done
    ev, record, pos_state = await done_slot(
        session=session,
        slot=slot,
        photo=photo,
        lat=lat,
        lon=lon,
        accuracy_m=accuracy_m,
        service_code=service_code,
    )
    session.commit()

    base_url = settings.public_base_url
    record_url = f"{base_url}/record/{record.token}" if base_url else f"/record/{record.token}"

    return SlotEvidenceOut(
        slot_id=slot.id,
        status=slot.status,
        evidence=EvidenceDetail(
            kind=ev.kind,
            lat=ev.lat,
            lon=ev.lon,
            accuracy_m=ev.accuracy_m,
            distance_to_plot_m=ev.distance_to_plot_m,
            plausible=ev.plausible,
            position_state=pos_state,
            photo="present" if ev.photo_path else "none",
            timestamp=clock.iso_z(ev.server_time),
        ),
        flags=slot.flags_json or [],
        needs_review=slot.needs_review,
        record_url=record_url,
    )


@router.post("/{id}/not-served", response_model=SlotOut)
def not_served_slot_endpoint(
    id: int,
    payload: NotServedIn,
    x_vaari_slot_token: str | None = Header(None, alias="X-Vaari-Slot-Token"),
    x_vaari_passcode: str | None = Header(None, alias="X-Vaari-Passcode"),
    principal: Principal | None = Depends(get_slot_caller),
    session: Session = Depends(get_db),
):
    slot = session.query(Slot).filter_by(id=id).first()
    if slot is None:
        raise VaariError("NOT_FOUND", "Slot not found.", 404)

    _check_slot_caller(session, slot, x_vaari_slot_token, x_vaari_passcode, principal)

    slot = not_served_slot(
        session=session,
        slot=slot,
        reason=payload.reason.value,
        note=payload.note,
    )
    session.commit()

    return serialize_slot(session, slot, include_link_token=True)


def _record_link_out(slot: Slot, record) -> dict[str, Any]:
    from app.tokens import link_state

    base_url = settings.public_base_url
    path = f"/record/{record.token}"
    return {
        "slot_id": slot.id,
        "record_token": record.token,
        "record_url": f"{base_url}{path}" if base_url else path,
        "status": link_state(record.token_expires_at, record.token_revoked_at),
        "expires_at": clock.iso_z(record.token_expires_at) if record.token_expires_at else None,
    }


def _record_for_slot(session: Session, slot_id: int):
    from app.models import ServiceRecord

    slot = session.query(Slot).filter_by(id=slot_id).first()
    if slot is None:
        raise VaariError("NOT_FOUND", "Slot not found.", 404)
    record = session.query(ServiceRecord).filter_by(slot_id=slot.id).first()
    if record is None:
        raise VaariError("NOT_FOUND", "This slot has no service record yet.", 404)
    return slot, record


@router.post("/{id}/record/revoke")
def revoke_record_link(
    id: int,
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
) -> dict[str, Any]:
    """Turn a service-record link off. The record itself and its hash are unchanged."""
    from app.event_log import log_event

    slot, record = _record_for_slot(session, id)
    if record.token_revoked_at is None:
        record.token_revoked_at = clock.now_utc()
        log_event(session, actor="operator", entity="service_record", entity_id=record.id, event="link_revoked")
    session.commit()
    return _record_link_out(slot, record)


@router.post("/{id}/record/reissue")
def reissue_record_link(
    id: int,
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
) -> dict[str, Any]:
    """Give a service record a new link. The old link stops working; the hash is unchanged."""
    from app.event_log import log_event
    from app.tokens import new_token, record_link_expiry

    slot, record = _record_for_slot(session, id)
    record.token = new_token()
    record.token_expires_at = record_link_expiry()
    record.token_revoked_at = None
    log_event(session, actor="operator", entity="service_record", entity_id=record.id, event="link_reissued")
    session.commit()
    return _record_link_out(slot, record)
