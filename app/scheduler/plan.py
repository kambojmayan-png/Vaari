"""Pure core scheduling algorithm for Vaari (Contract Section 8).

Pure function: no database, no clock, no network, no randomness.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.enums import from_x100
from app.scheduler.distance import estimated_distance_km
from app.scheduler.reasons import (
    deadline_passed_reason,
    invalid_request_reason,
    machine_unavailable_reason,
    no_capacity_reason,
    no_compatible_machine_reason,
    scheduled_reason,
    travel_infeasible_reason,
)


@dataclass(frozen=True)
class RequestIn:
    id: int
    created_at: datetime
    service_type: str
    acres_x100: int
    harvest_date: date | None
    deadline_date: date | None
    lat: float | None = None
    lon: float | None = None


@dataclass(frozen=True)
class MachineIn:
    id: int
    service_types: tuple[str, ...]
    capacity_acres_x100: int
    status: str
    active_from: date | None = None
    active_to: date | None = None
    name: str | None = None


@dataclass(frozen=True)
class CentreIn:
    id: int
    name: str
    lat: float
    lon: float
    is_home: bool
    service_types: tuple[str, ...]


@dataclass(frozen=True)
class ExistingSlot:
    machine_id: int
    service_date: date
    acres_x100: int
    lat: float | None = None
    lon: float | None = None
    request_id: int | None = None


@dataclass(frozen=True)
class Settings:
    max_radius_km: float = 25.0
    road_factor: float = 1.3


@dataclass
class Assignment:
    request_id: int
    machine_id: int
    service_date: date
    seq: int
    est_distance_km: float
    explanation: str


@dataclass
class Miss:
    request_id: int
    reason_code: str
    reason: str
    data_used: dict[str, Any]
    next_action: str | None
    nearest_alternative: str | None
    alternative_distance_km: float | None


@dataclass
class Plan:
    assignments: list[Assignment]
    misses: list[Miss]


def days_inclusive(start: date, end: date) -> Iterator[date]:
    """Yield every date from start to end inclusive."""
    curr = start
    while curr <= end:
        yield curr
        curr += timedelta(days=1)


def find_nearest_alternative(
    centres: list[CentreIn],
    req: RequestIn,
    service_type: str,
    road_factor: float,
) -> tuple[CentreIn | None, float | None]:
    """Find the nearest non-home centre offering the requested service type."""
    eligible = [
        c for c in centres
        if not c.is_home and service_type in c.service_types
    ]
    if not eligible:
        return None, None

    scored = []
    for c in eligible:
        dist = estimated_distance_km(c.lat, c.lon, req.lat, req.lon, road_factor)
        scored.append((dist, c.id, c))

    scored.sort(key=lambda x: (x[0], x[1]))
    best_dist, _, best_centre = scored[0]
    return best_centre, best_dist


def plan(
    requests: list[RequestIn],
    machines: list[MachineIn],
    centres: list[CentreIn],
    existing_slots: list[ExistingSlot],
    today: date,
    settings: Settings,
) -> Plan:
    """Deterministic, pure deadline-first scheduler."""
    # Find home centre
    home_centre = next((c for c in centres if c.is_home), None)
    if home_centre is None and centres:
        home_centre = centres[0]
    home_lat = home_centre.lat if home_centre else 0.0
    home_lon = home_centre.lon if home_centre else 0.0

    def _sort_key(r: RequestIn):
        c_at = r.created_at
        if c_at is not None and c_at.tzinfo is None:
            c_at = c_at.replace(tzinfo=timezone.utc)
        return (
            r.deadline_date if r.deadline_date is not None else date.max,
            c_at,
            r.id,
        )

    # 1. Sort requests: deadline_date, created_at, id
    sorted_requests = sorted(requests, key=_sort_key)

    # Track capacity per (machine_id, date) in integer hundredths
    used_capacity: dict[tuple[int, date], int] = {}
    slots_on_day: dict[tuple[int, date], list[dict[str, Any]]] = {}

    for s in existing_slots:
        key = (s.machine_id, s.service_date)
        used_capacity[key] = used_capacity.get(key, 0) + s.acres_x100
        slots_on_day.setdefault(key, []).append({
            "request_id": s.request_id or 0,
            "lat": s.lat,
            "lon": s.lon,
            "is_existing": True,
        })

    assignments: list[Assignment] = []
    misses: list[Miss] = []


    for req in sorted_requests:
        # 2. Validity check
        if (
            req.acres_x100 is None
            or req.acres_x100 < 25
            or req.acres_x100 > 20000
            or req.deadline_date is None
            or (req.harvest_date is not None and req.deadline_date < req.harvest_date)
        ):
            reason, next_action = invalid_request_reason("dates conflict or invalid acres")
            misses.append(
                Miss(
                    request_id=req.id,
                    reason_code="INVALID_REQUEST",
                    reason=reason,
                    data_used={"acres": req.acres_x100 / 100.0 if req.acres_x100 else 0},
                    next_action=next_action,
                    nearest_alternative=None,
                    alternative_distance_km=None,
                )
            )
            continue

        # 3. Deadline passed
        if req.deadline_date < today:
            reason, next_action = deadline_passed_reason(req.deadline_date, today)
            misses.append(
                Miss(
                    request_id=req.id,
                    reason_code="DEADLINE_PASSED",
                    reason=reason,
                    data_used={"deadline_date": str(req.deadline_date), "today": str(today)},
                    next_action=next_action,
                    nearest_alternative=None,
                    alternative_distance_km=None,
                )
            )
            continue

        # 4. Compatible machines
        compat_machines = [
            m for m in machines
            if req.service_type in m.service_types
        ]
        compat_machines.sort(key=lambda m: m.id)

        if not compat_machines:
            alt_c, alt_dist = find_nearest_alternative(centres, req, req.service_type, settings.road_factor)
            reason, next_action = no_compatible_machine_reason(
                req.service_type,
                alt_name=alt_c.name if alt_c else None,
                alt_dist=alt_dist,
            )
            misses.append(
                Miss(
                    request_id=req.id,
                    reason_code="NO_COMPATIBLE_MACHINE",
                    reason=reason,
                    data_used={"service_type": req.service_type},
                    next_action=next_action,
                    nearest_alternative=alt_c.name if alt_c else None,
                    alternative_distance_km=alt_dist,
                )
            )
            continue

        # 5. Estimated distance
        est_dist = estimated_distance_km(
            home_lat, home_lon, req.lat, req.lon, settings.road_factor
        )

        # 6. Search days
        start_day = max(today, req.harvest_date) if req.harvest_date else today
        assigned = False

        if start_day <= req.deadline_date:
            for day in days_inclusive(start_day, req.deadline_date):
                candidates_on_day = []
                for m in compat_machines:
                    if m.status == "inactive":
                        continue
                    if m.active_from and day < m.active_from:
                        continue
                    if m.active_to and day > m.active_to:
                        continue
                    if est_dist > settings.max_radius_km:
                        continue

                    key = (m.id, day)
                    used = used_capacity.get(key, 0)
                    free = m.capacity_acres_x100 - used
                    if free < req.acres_x100:
                        continue

                    # Calculate cost: smallest estimated distance to centre or existing assignments
                    cost = est_dist
                    for existing in slots_on_day.get(key, []):
                        d_cand = estimated_distance_km(
                            req.lat, req.lon, existing["lat"], existing["lon"], settings.road_factor
                        )
                        if d_cand < cost:
                            cost = d_cand

                    candidates_on_day.append((cost, m.id, m))

                if candidates_on_day:
                    # Pick lowest cost, break ties on lower machine id
                    candidates_on_day.sort(key=lambda x: (x[0], x[1]))
                    _, best_m_id, best_m = candidates_on_day[0]

                    key = (best_m_id, day)
                    used_capacity[key] = used_capacity.get(key, 0) + req.acres_x100
                    slots_on_day.setdefault(key, []).append({
                        "request_id": req.id,
                        "lat": req.lat,
                        "lon": req.lon,
                        "is_existing": False,
                    })

                    machine_name = best_m.name or f"Machine {best_m.id}"
                    reason, _ = scheduled_reason(
                        service_date=day,
                        machine_name=machine_name,
                        acres_x100=req.acres_x100,
                        deadline_date=req.deadline_date,
                    )

                    assignments.append(
                        Assignment(
                            request_id=req.id,
                            machine_id=best_m_id,
                            service_date=day,
                            seq=0,  # will be renumbered below
                            est_distance_km=est_dist,
                            explanation=reason,
                        )
                    )
                    assigned = True
                    break

        if not assigned:
            # 8. Reason order when nothing fits:
            # MACHINE_UNAVAILABLE -> TRAVEL_INFEASIBLE -> NO_CAPACITY
            alt_c, alt_dist = find_nearest_alternative(centres, req, req.service_type, settings.road_factor)

            # Check if any compatible machine is active on any day in the window
            any_active_in_window = False
            if start_day <= req.deadline_date:
                for day in days_inclusive(start_day, req.deadline_date):
                    for m in compat_machines:
                        if m.status != "inactive":
                            if (m.active_from is None or day >= m.active_from) and (
                                m.active_to is None or day <= m.active_to
                            ):
                                any_active_in_window = True
                                break
                    if any_active_in_window:
                        break

            if not any_active_in_window:
                reason, next_action = machine_unavailable_reason(
                    service_type=req.service_type,
                    start_day=start_day,
                    deadline_date=req.deadline_date,
                    alt_name=alt_c.name if alt_c else None,
                    alt_dist=alt_dist,
                )
                misses.append(
                    Miss(
                        request_id=req.id,
                        reason_code="MACHINE_UNAVAILABLE",
                        reason=reason,
                        data_used={
                            "service_type": req.service_type,
                            "start_day": str(start_day),
                            "deadline_date": str(req.deadline_date),
                        },
                        next_action=next_action,
                        nearest_alternative=alt_c.name if alt_c else None,
                        alternative_distance_km=alt_dist,
                    )
                )
            elif est_dist > settings.max_radius_km:
                reason, next_action = travel_infeasible_reason(
                    est_distance_km=est_dist,
                    max_radius_km=settings.max_radius_km,
                    alt_name=alt_c.name if alt_c else None,
                    alt_dist=alt_dist,
                )
                misses.append(
                    Miss(
                        request_id=req.id,
                        reason_code="TRAVEL_INFEASIBLE",
                        reason=reason,
                        data_used={
                            "distance_km": est_dist,
                            "max_radius_km": settings.max_radius_km,
                        },
                        next_action=next_action,
                        nearest_alternative=alt_c.name if alt_c else None,
                        alternative_distance_km=alt_dist,
                    )
                )
            else:
                reason, next_action = no_capacity_reason(
                    acres_x100=req.acres_x100,
                    deadline_date=req.deadline_date,
                    alt_name=alt_c.name if alt_c else None,
                    alt_dist=alt_dist,
                )
                misses.append(
                    Miss(
                        request_id=req.id,
                        reason_code="NO_CAPACITY",
                        reason=reason,
                        data_used={
                            "acres": from_x100(req.acres_x100),
                            "deadline_date": str(req.deadline_date),
                        },
                        next_action=next_action,
                        nearest_alternative=alt_c.name if alt_c else None,
                        alternative_distance_km=alt_dist,
                    )
                )

    # Renumber seq on each touched machine-day using nearest neighbour
    # Group assignments by (machine_id, service_date)
    touched_days: set[tuple[int, date]] = {
        (a.machine_id, a.service_date) for a in assignments
    }

    seq_map: dict[int, int] = {}

    for key in sorted(touched_days):
        items = list(slots_on_day.get(key, []))
        if not items:
            continue

        # Nearest neighbour tour starting from home centre
        current_lat = home_lat
        current_lon = home_lon
        remaining = list(items)
        seq_num = 1

        while remaining:
            # Sort candidate next stops by distance from current_pos, ties broken by request_id
            candidates = []
            for item in remaining:
                dist = estimated_distance_km(
                    current_lat, current_lon, item["lat"], item["lon"], settings.road_factor
                )
                candidates.append((dist, item["request_id"], item))

            candidates.sort(key=lambda x: (x[0], x[1]))
            _, chosen_req_id, chosen_item = candidates[0]
            seq_map[chosen_req_id] = seq_num
            seq_num += 1

            if chosen_item["lat"] is not None and chosen_item["lon"] is not None:
                current_lat = chosen_item["lat"]
                current_lon = chosen_item["lon"]

            remaining.remove(chosen_item)

    for a in assignments:
        a.seq = seq_map.get(a.request_id, 1)

    return Plan(assignments=assignments, misses=misses)
