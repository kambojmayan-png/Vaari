"""Common route helpers and model serializers."""

from sqlalchemy.orm import Session

from app import clock
from app.config import settings
from app.enums import from_x100
from app.models import Centre, Farmer, Machine, Plot, Request, ServiceRecord, Slot
from app.schemas import (
    ExplanationBrief,
    FarmerBrief,
    LocationBrief,
    MachineBrief,
    MachineOut,
    PlotOut,
    RequestOut,
    SlotBrief,
    SlotOut,
)
from app.tokens import link_state


def get_or_create_home_centre(session: Session) -> Centre:
    """Ensure exactly one home centre exists, creating it from settings if needed."""
    centre = session.query(Centre).filter_by(is_home=True).first()
    if centre is None:
        centre = Centre(
            name=settings.centre_name,
            phone=settings.centre_phone,
            lat=settings.centre_lat,
            lon=settings.centre_lon,
            is_home=True,
            service_types=["super_seeder", "happy_seeder", "baler", "mulcher"],
        )
        session.add(centre)
        session.flush()
    return centre


def serialize_request(session: Session, req: Request) -> RequestOut:
    farmer = session.query(Farmer).filter_by(id=req.farmer_id).first()
    plot = session.query(Plot).filter_by(id=req.plot_id).first()
    slot = session.query(Slot).filter_by(request_id=req.id).filter(Slot.status != "cancelled").first()

    slot_brief = None
    if slot is not None:
        machine = session.query(Machine).filter_by(id=slot.machine_id).first()
        machine_name = machine.name if machine else "Unknown"
        slot_brief = SlotBrief(
            id=slot.id,
            machine_id=slot.machine_id,
            machine_name=machine_name,
            service_date=slot.service_date,
            seq=slot.seq,
            status=slot.status,
        )

    badges = []
    if req.source == "seed":
        badges.append("seeded request")
    if farmer and farmer.consent_simulated:
        badges.append("consent simulated")

    return RequestOut(
        id=req.id,
        status=req.status,
        source=req.source,
        farmer=FarmerBrief(name=farmer.name if farmer else None, phone=farmer.phone if farmer else ""),
        village=plot.village_name if plot else "",
        acres=from_x100(req.acres_x100),
        service_type=req.service_type,
        harvest_date=req.harvest_date,
        sow_by=req.sow_by,
        deadline_date=req.deadline_date,
        explanation=ExplanationBrief(
            reason_code=req.reason_code,
            reason=req.reason,
            data_used=req.data_used_json or {},
            next_action=req.next_action,
            nearest_alternative=req.nearest_alternative,
            alternative_distance_km=req.alternative_distance_km,
        ),
        slot=slot_brief,
        badges=badges,
        created_at=clock.iso_z(req.created_at),
    )


def serialize_machine(machine: Machine) -> MachineOut:
    return MachineOut(
        id=machine.id,
        name=machine.name,
        type=machine.type,
        service_types=machine.service_types or [],
        capacity_acres_per_day=from_x100(machine.capacity_acres_x100),
        status=machine.status,
        active_from=machine.active_from,
        active_to=machine.active_to,
        driver_path=f"/driver/{machine.link_token}",
        driver_link_status=link_state(machine.link_expires_at, machine.link_revoked_at),
        driver_link_expires_at=clock.iso_z(machine.link_expires_at) if machine.link_expires_at else None,
    )


def serialize_plot(plot: Plot, warning: str | None = None) -> PlotOut:
    return PlotOut(
        id=plot.id,
        farmer_id=plot.farmer_id,
        village_name=plot.village_name,
        acres=from_x100(plot.acres_x100),
        pin_lat=plot.pin_lat,
        pin_lon=plot.pin_lon,
        centroid_lat=plot.centroid_lat,
        centroid_lon=plot.centroid_lon,
        location_source=plot.location_source,
        geojson=plot.geojson,
        warning=warning,
    )


def serialize_slot(session: Session, slot: Slot, include_link_token: bool = True) -> SlotOut:
    machine = session.query(Machine).filter_by(id=slot.machine_id).first()
    req = session.query(Request).filter_by(id=slot.request_id).first()
    farmer = session.query(Farmer).filter_by(id=req.farmer_id).first() if req else None
    plot = session.query(Plot).filter_by(id=req.plot_id).first() if req else None
    service_rec = session.query(ServiceRecord).filter_by(slot_id=slot.id).first()

    loc_lat = plot.pin_lat if plot else None
    loc_lon = plot.pin_lon if plot else None
    loc_source = plot.location_source if plot else "none"

    return SlotOut(
        id=slot.id,
        seq=slot.seq,
        status=slot.status,
        service_date=slot.service_date,
        machine=MachineBrief(id=machine.id if machine else 0, name=machine.name if machine else "Unknown"),
        request_id=slot.request_id,
        farmer_name=farmer.name if farmer else None,
        village=plot.village_name if plot else "",
        acres=from_x100(req.acres_x100) if req else 0.0,
        deadline_date=req.deadline_date if req else None,
        location=LocationBrief(lat=loc_lat, lon=loc_lon, source=loc_source),
        est_distance_km=slot.est_distance_km,
        link_token=slot.link_token if include_link_token else None,
        needs_review=slot.needs_review,
        flags=slot.flags_json or [],
        started_at=clock.iso_z(slot.started_at) if slot.started_at else None,
        done_at=clock.iso_z(slot.done_at) if slot.done_at else None,
        record_token=service_rec.token if service_rec else None,
    )
