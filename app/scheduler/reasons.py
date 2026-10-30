"""Explanation and next_action templates for scheduler outcomes (Contract Section 8)."""

from datetime import date

from app.clock import fmt_en
from app.enums import from_x100

SERVICE_DISPLAY = {
    "super_seeder": "super seeder",
    "happy_seeder": "happy seeder",
    "baler": "baler",
    "mulcher": "mulcher",
}


def format_acres(acres_x100: int) -> str:
    val = from_x100(acres_x100)
    # If integer value like 4.0, format as 4 or 4.0? Let's check contract: "3.2", "2.5", "6"
    return f"{val:g}"


def scheduled_reason(
    service_date: date,
    machine_name: str,
    acres_x100: int,
    deadline_date: date,
) -> tuple[str, None]:
    acres_str = format_acres(acres_x100)
    reason = (
        f"Scheduled on {fmt_en(service_date)} on {machine_name}: "
        f"the earliest day with {acres_str} free acres before the deadline of {fmt_en(deadline_date)}."
    )
    return reason, None


def invalid_request_reason(problem: str) -> tuple[str, str]:
    reason = f"This request is incomplete or its dates conflict: {problem}."
    next_action = "Correct the request."
    return reason, next_action


def deadline_passed_reason(deadline_date: date, today: date) -> tuple[str, str]:
    reason = f"The deadline of {fmt_en(deadline_date)} is before today ({fmt_en(today)})."
    next_action = "Call the farmer and record the outcome."
    return reason, next_action


def no_compatible_machine_reason(
    service_type: str,
    alt_name: str | None = None,
    alt_dist: float | None = None,
) -> tuple[str, str]:
    display = SERVICE_DISPLAY.get(service_type, service_type)
    reason = f"This centre has no machine for {display} work."
    if alt_name and alt_dist is not None:
        next_action = f"Refer to {alt_name}, {alt_dist} km away."
    else:
        next_action = "Refer to another centre."
    return reason, next_action


def machine_unavailable_reason(
    service_type: str,
    start_day: date,
    deadline_date: date,
    alt_name: str | None = None,
    alt_dist: float | None = None,
) -> tuple[str, str]:
    display = SERVICE_DISPLAY.get(service_type, service_type)
    reason = (
        f"Every {display} machine is inactive between {fmt_en(start_day)} "
        f"and {fmt_en(deadline_date)}."
    )
    if alt_name and alt_dist is not None:
        next_action = f"Check repairs, or ask {alt_name}, {alt_dist} km away."
    else:
        next_action = "Check repairs, or ask another centre."
    return reason, next_action


def travel_infeasible_reason(
    est_distance_km: float,
    max_radius_km: float,
    alt_name: str | None = None,
    alt_dist: float | None = None,
) -> tuple[str, str]:
    radius_str = f"{int(max_radius_km)}" if max_radius_km.is_integer() else f"{max_radius_km}"
    reason = (
        f"The field is about {est_distance_km} km away, "
        f"beyond the {radius_str} km service radius."
    )
    if alt_name and alt_dist is not None:
        next_action = f"Refer to {alt_name}, {alt_dist} km away."
    else:
        next_action = "Refer to another centre."
    return reason, next_action


def no_capacity_reason(
    acres_x100: int,
    deadline_date: date,
    alt_name: str | None = None,
    alt_dist: float | None = None,
) -> tuple[str, str]:
    acres_str = format_acres(acres_x100)
    reason = f"No compatible machine has {acres_str} free acres on or before {fmt_en(deadline_date)}."
    if alt_name and alt_dist is not None:
        next_action = f"Ask {alt_name}, {alt_dist} km away."
    else:
        next_action = "Ask another centre."
    return reason, next_action
