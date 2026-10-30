"""Scheduler service: loads DB rows into dataclasses, runs pure plan(), saves results."""

import time
from datetime import timezone
from typing import Any

from sqlalchemy.orm import Session

from app import clock
from app.config import settings
from app.event_log import log_event
from app.models import Centre, Machine, Plot, Request, Slot
from app.scheduler.plan import (
    CentreIn,
    ExistingSlot,
    MachineIn,
    RequestIn,
    plan,
)
from app.scheduler.plan import (
    Settings as SchedulerSettings,
)
from app.tokens import new_service_code, new_token


def run_for_centre(session: Session, centre_id: int) -> dict[str, Any]:
    """Execute the scheduler for a centre within the caller's session."""
    t0 = time.perf_counter()

    # 1. Centres
    centres_orm = session.query(Centre).order_by(Centre.id.asc()).all()
    centres = [
        CentreIn(
            id=c.id,
            name=c.name,
            lat=c.lat,
            lon=c.lon,
            is_home=c.is_home,
            service_types=tuple(c.service_types or []),
        )
        for c in centres_orm
    ]

    # 2. Machines for this centre
    machines_orm = (
        session.query(Machine)
        .filter_by(centre_id=centre_id)
        .order_by(Machine.id.asc())
        .all()
    )
    machines = [
        MachineIn(
            id=m.id,
            name=m.name,
            service_types=tuple(m.service_types or []),
            capacity_acres_x100=m.capacity_acres_x100,
            status=m.status,
            active_from=m.active_from,
            active_to=m.active_to,
        )
        for m in machines_orm
    ]

    # 3. Active existing slots for capacity calculation
    active_slots_orm = (
        session.query(Slot)
        .join(Machine, Slot.machine_id == Machine.id)
        .filter(
            Machine.centre_id == centre_id,
            Slot.status.in_(["scheduled", "in_progress", "done"]),
        )
        .order_by(Slot.id.asc())
        .all()
    )

    existing_slots = []
    active_slot_request_ids = set()
    for s in active_slots_orm:
        active_slot_request_ids.add(s.request_id)
        r = session.query(Request).filter_by(id=s.request_id).first()
        p = session.query(Plot).filter_by(id=r.plot_id).first() if r else None
        lat = (p.centroid_lat if p and p.centroid_lat else (p.pin_lat if p else None))
        lon = (p.centroid_lon if p and p.centroid_lon else (p.pin_lon if p else None))
        acres_x100 = r.acres_x100 if r else 0
        existing_slots.append(
            ExistingSlot(
                machine_id=s.machine_id,
                service_date=s.service_date,
                acres_x100=acres_x100,
                lat=lat,
                lon=lon,
                request_id=s.request_id,
            )
        )

    # 4. Open and will_miss requests to plan
    requests_orm = (
        session.query(Request)
        .filter(
            Request.centre_id == centre_id,
            Request.status.in_(["open", "will_miss"]),
        )
        .order_by(
            Request.deadline_date.asc().nullslast(),
            Request.created_at.asc(),
            Request.id.asc(),
        )
        .all()
    )

    requests_to_plan = []
    for r in requests_orm:
        if r.id in active_slot_request_ids:
            continue
        p = session.query(Plot).filter_by(id=r.plot_id).first()
        lat = (p.centroid_lat if p and p.centroid_lat else (p.pin_lat if p else None))
        lon = (p.centroid_lon if p and p.centroid_lon else (p.pin_lon if p else None))
        c_at = r.created_at
        if c_at is not None and c_at.tzinfo is None:
            c_at = c_at.replace(tzinfo=timezone.utc)
        requests_to_plan.append(
            RequestIn(
                id=r.id,
                created_at=c_at,
                service_type=r.service_type,
                acres_x100=r.acres_x100,
                harvest_date=r.harvest_date,
                deadline_date=r.deadline_date,
                lat=lat,
                lon=lon,
            )
        )

    # 5. Run pure plan()
    today = clock.today()
    sched_settings = SchedulerSettings(
        max_radius_km=settings.max_radius_km,
        road_factor=settings.road_factor,
    )
    plan_result = plan(
        requests=requests_to_plan,
        machines=machines,
        centres=centres,
        existing_slots=existing_slots,
        today=today,
        settings=sched_settings,
    )

    # 6. Apply Assignments
    now = clock.now_utc()
    for a in plan_result.assignments:
        req = session.query(Request).filter_by(id=a.request_id).first()
        if not req:
            continue
        req.status = "scheduled"
        req.reason = a.explanation
        req.reason_code = None
        req.next_action = None
        req.data_used_json = None
        req.nearest_alternative = None
        req.alternative_distance_km = None
        req.updated_at = now

        # Create slot
        slot = Slot(
            request_id=req.id,
            machine_id=a.machine_id,
            service_date=a.service_date,
            seq=a.seq,
            status="scheduled",
            link_token=new_token(),
            service_code=new_service_code(),
            est_distance_km=a.est_distance_km,
            created_at=now,
            flags_json=[],
            needs_review=False,
        )
        session.add(slot)
        session.flush()

        log_event(
            session=session,
            actor="system",
            entity="slot",
            entity_id=slot.id,
            event="created",
            payload={
                "machine_id": a.machine_id,
                "service_date": str(a.service_date),
                "seq": a.seq,
            },
        )
        log_event(
            session=session,
            actor="system",
            entity="request",
            entity_id=req.id,
            event="scheduled",
            payload={
                "slot_id": slot.id,
                "machine_id": a.machine_id,
                "service_date": str(a.service_date),
            },
        )

    # 7. Apply Misses
    for m in plan_result.misses:
        req = session.query(Request).filter_by(id=m.request_id).first()
        if not req:
            continue
        req.status = "will_miss"
        req.reason_code = m.reason_code
        req.reason = m.reason
        req.data_used_json = m.data_used
        req.next_action = m.next_action
        req.nearest_alternative = m.nearest_alternative
        req.alternative_distance_km = m.alternative_distance_km
        req.updated_at = now

        log_event(
            session=session,
            actor="system",
            entity="request",
            entity_id=req.id,
            event="will_miss",
            payload={"reason_code": m.reason_code},
        )

    session.flush()

    # 8. Compute counts
    all_requests = session.query(Request).filter_by(centre_id=centre_id).all()
    counts = {
        "total": len(all_requests),
        "needs_info": sum(1 for r in all_requests if r.status == "needs_info"),
        "open": sum(1 for r in all_requests if r.status == "open"),
        "scheduled": sum(1 for r in all_requests if r.status == "scheduled"),
        "done": sum(1 for r in all_requests if r.status == "done"),
        "will_miss": sum(1 for r in all_requests if r.status == "will_miss"),
        "cancelled": sum(1 for r in all_requests if r.status == "cancelled"),
        "ran_in_ms": int((time.perf_counter() - t0) * 1000),
        "today": today.isoformat(),
    }
    return counts
