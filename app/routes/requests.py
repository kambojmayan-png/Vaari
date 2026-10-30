"""API routes for managing requests (Contract Section 11)."""

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app import clock
from app.auth import Principal, require_operator
from app.db import get_db
from app.enums import ServiceType, to_x100
from app.errors import VaariError
from app.event_log import log_event
from app.models import Farmer, Plot, Request, Slot, Village
from app.routes.common import get_or_create_home_centre, serialize_request
from app.scheduler.dates import compute_dates
from app.scheduler.service import run_for_centre
from app.schemas import RequestIn, RequestOut, RequestPatch

router = APIRouter(prefix="/requests", tags=["requests"])


def create_request_record(
    session: Session,
    payload: RequestIn,
    source: str = "form",
    run_scheduler: bool = True,
    extra_log_payload: dict | None = None,
) -> Request:
    """Shared service function to create a Farmer, Plot, and Request row."""
    if not payload.consent_service:
        raise VaariError(
            error_code="VALIDATION_ERROR",
            message="Consent for service is required.",
            http_status=422,
            details={"field": "consent_service"},
        )

    home_centre = get_or_create_home_centre(session)

    # 1. Upsert farmer
    farmer = session.query(Farmer).filter_by(phone=payload.phone).first()
    now = clock.now_utc()
    if farmer is None:
        farmer = Farmer(
            phone=payload.phone,
            name=payload.name,
            language="pa",
            consent_service=payload.consent_service,
            consent_evidence=payload.consent_evidence,
            consent_share=payload.consent_share,
            consent_at=now,
            consent_simulated=True,
        )
        session.add(farmer)
        session.flush()
    else:
        if payload.name:
            farmer.name = payload.name
        farmer.consent_service = payload.consent_service
        farmer.consent_evidence = payload.consent_evidence
        farmer.consent_share = payload.consent_share
        farmer.consent_at = now
        session.flush()

    # 2. Location & Plot
    village = session.query(Village).filter_by(name=payload.village).first()
    village_id = village.id if village else None

    if payload.lat is not None and payload.lon is not None:
        location_source = "pin"
        pin_lat, pin_lon = payload.lat, payload.lon
    elif village is not None:
        location_source = "village"
        pin_lat, pin_lon = village.lat, village.lon
    else:
        location_source = "none"
        pin_lat, pin_lon = None, None

    acres_x100 = to_x100(payload.acres)
    plot = Plot(
        farmer_id=farmer.id,
        village_name=payload.village,
        village_id=village_id,
        pin_lat=pin_lat,
        pin_lon=pin_lon,
        geojson=None,
        acres_x100=acres_x100,
        centroid_lat=pin_lat,
        centroid_lon=pin_lon,
        location_source=location_source,
    )
    session.add(plot)
    session.flush()

    # 3. Dates & Status
    service_val = (
        payload.service_type.value
        if isinstance(payload.service_type, ServiceType)
        else str(payload.service_type)
    )
    sow_by, deadline_date, deadline_overridden = compute_dates(
        harvest_date=payload.harvest_date,
        service_type=service_val,
        given_deadline=payload.deadline_date,
    )

    req_status = "open" if payload.harvest_date is not None else "needs_info"

    req = Request(
        centre_id=home_centre.id,
        farmer_id=farmer.id,
        plot_id=plot.id,
        service_type=service_val,
        source=source,
        acres_x100=acres_x100,
        harvest_date=payload.harvest_date,
        sow_by=sow_by,
        deadline_date=deadline_date,
        deadline_overridden=deadline_overridden,
        status=req_status,
        reason_code=None,
        reason=None,
        next_action=None,
        data_used_json=None,
        nearest_alternative=None,
        alternative_distance_km=None,
        created_at=now,
        updated_at=now,
    )
    session.add(req)
    session.flush()

    log_payload = {"source": source}
    if extra_log_payload:
        log_payload.update(extra_log_payload)

    log_event(
        session=session,
        actor="operator",
        entity="request",
        entity_id=req.id,
        event="created",
        payload=log_payload,
    )

    if run_scheduler:
        run_for_centre(session, home_centre.id)

    return req


@router.post("", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: RequestIn,
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
):
    req = create_request_record(
        session=session,
        payload=payload,
        source="form",
        run_scheduler=True,
    )
    session.commit()
    return serialize_request(session, req)


@router.get("", response_model=list[RequestOut])
def list_requests(
    status: str | None = Query(None),
    village: str | None = Query(None),
    date: date | None = Query(None),
    service_type: str | None = Query(None),
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
):
    query = session.query(Request)

    if status:
        query = query.filter(Request.status == status)
    if service_type:
        query = query.filter(Request.service_type == service_type)
    if village:
        query = query.join(Plot, Request.plot_id == Plot.id).filter(Plot.village_name == village)
    if date:
        query = query.join(Slot, Request.id == Slot.request_id).filter(
            Slot.service_date == date, Slot.status != "cancelled"
        )

    query = query.order_by(Request.deadline_date.asc().nullslast(), Request.id.asc())
    results = query.all()
    return [serialize_request(session, r) for r in results]


@router.get("/{id}", response_model=RequestOut)
def get_request(
    id: int,
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
):
    req = session.query(Request).filter_by(id=id).first()
    if req is None:
        raise VaariError("NOT_FOUND", "Request not found.", 404)
    return serialize_request(session, req)


@router.patch("/{id}", response_model=RequestOut)
def patch_request(
    id: int,
    payload: RequestPatch,
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
):
    req = session.query(Request).filter_by(id=id).first()
    if req is None:
        raise VaariError("NOT_FOUND", "Request not found.", 404)

    if req.status in ("done", "cancelled"):
        raise VaariError(
            error_code="INVALID_TRANSITION",
            message=f"Cannot patch a request in {req.status} status.",
            http_status=409,
        )

    slot = session.query(Slot).filter_by(request_id=req.id).filter(Slot.status != "cancelled").first()
    if slot is not None:
        if slot.status in ("in_progress", "done"):
            raise VaariError(
                error_code="INVALID_TRANSITION",
                message=f"Cannot modify request: slot is already {slot.status}.",
                http_status=409,
            )
        slot.status = "cancelled"

    farmer = session.query(Farmer).filter_by(id=req.farmer_id).first()
    plot = session.query(Plot).filter_by(id=req.plot_id).first()

    if payload.name is not None and farmer:
        farmer.name = payload.name

    if payload.village is not None and plot:
        plot.village_name = payload.village
        v = session.query(Village).filter_by(name=payload.village).first()
        plot.village_id = v.id if v else None

    if payload.acres is not None:
        req.acres_x100 = to_x100(payload.acres)
        if plot:
            plot.acres_x100 = req.acres_x100

    if payload.service_type is not None:
        req.service_type = payload.service_type.value

    if payload.lat is not None or payload.lon is not None:
        if plot:
            plot.pin_lat = payload.lat if payload.lat is not None else plot.pin_lat
            plot.pin_lon = payload.lon if payload.lon is not None else plot.pin_lon
            plot.centroid_lat = plot.pin_lat
            plot.centroid_lon = plot.pin_lon
            plot.location_source = "pin"

    new_harvest = payload.harvest_date if payload.harvest_date is not None else req.harvest_date
    if payload.deadline_date is not None:
        new_deadline = payload.deadline_date
        sow_by, deadline_date, deadline_overridden = compute_dates(
            harvest_date=new_harvest,
            service_type=req.service_type,
            given_deadline=new_deadline,
        )
    elif payload.harvest_date is not None:
        given_deadline = req.deadline_date if req.deadline_overridden else None
        sow_by, deadline_date, deadline_overridden = compute_dates(
            harvest_date=new_harvest,
            service_type=req.service_type,
            given_deadline=given_deadline,
        )
    else:
        sow_by, deadline_date, deadline_overridden = req.sow_by, req.deadline_date, req.deadline_overridden

    req.harvest_date = new_harvest
    req.sow_by = sow_by
    req.deadline_date = deadline_date
    req.deadline_overridden = deadline_overridden
    req.status = "open" if req.harvest_date is not None else "needs_info"
    req.updated_at = clock.now_utc()

    log_event(
        session=session,
        actor="operator",
        entity="request",
        entity_id=req.id,
        event="patched",
        payload=payload.model_dump(exclude_unset=True),
    )

    home_centre = get_or_create_home_centre(session)
    run_for_centre(session, home_centre.id)
    session.commit()

    return serialize_request(session, req)


@router.delete("/{id}", response_model=RequestOut)
def delete_request(
    id: int,
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
):
    req = session.query(Request).filter_by(id=id).first()
    if req is None:
        raise VaariError("NOT_FOUND", "Request not found.", 404)

    slot = session.query(Slot).filter_by(request_id=req.id).filter(Slot.status != "cancelled").first()
    if slot is not None:
        if slot.status in ("in_progress", "done"):
            raise VaariError(
                error_code="INVALID_TRANSITION",
                message=f"Cannot cancel request: slot is already {slot.status}.",
                http_status=409,
            )
        slot.status = "cancelled"

    req.status = "cancelled"
    req.updated_at = clock.now_utc()

    log_event(
        session=session,
        actor="operator",
        entity="request",
        entity_id=req.id,
        event="cancelled",
    )
    session.commit()

    return serialize_request(session, req)
