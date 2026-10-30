"""Enums and units for Vaari."""

from decimal import ROUND_HALF_UP, Decimal
from enum import Enum


class ServiceType(str, Enum):
    SUPER_SEEDER = "super_seeder"
    HAPPY_SEEDER = "happy_seeder"
    BALER = "baler"
    MULCHER = "mulcher"


class RequestStatus(str, Enum):
    NEEDS_INFO = "needs_info"
    OPEN = "open"
    SCHEDULED = "scheduled"
    DONE = "done"
    WILL_MISS = "will_miss"
    CANCELLED = "cancelled"


class RequestSource(str, Enum):
    FORM = "form"
    REGISTER = "register"
    SEED = "seed"


class SlotStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    NOT_SERVED = "not_served"
    CANCELLED = "cancelled"


class ReasonCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    DEADLINE_PASSED = "DEADLINE_PASSED"
    NO_COMPATIBLE_MACHINE = "NO_COMPATIBLE_MACHINE"
    MACHINE_UNAVAILABLE = "MACHINE_UNAVAILABLE"
    TRAVEL_INFEASIBLE = "TRAVEL_INFEASIBLE"
    NO_CAPACITY = "NO_CAPACITY"


class NotServedReason(str, Enum):
    FIELD_NOT_READY = "FIELD_NOT_READY"
    FARMER_ABSENT = "FARMER_ABSENT"
    MACHINE_BROKEN = "MACHINE_BROKEN"
    WEATHER = "WEATHER"
    OTHER = "OTHER"


class LocationSource(str, Enum):
    PIN = "pin"
    POLYGON = "polygon"
    VILLAGE = "village"
    NONE = "none"


class MachineStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class EvidenceKind(str, Enum):
    START = "start"
    DONE = "done"
    EXTRA = "extra"


class EvidenceFlag(str, Enum):
    POSITION_MISMATCH = "position_mismatch"
    TOO_FAST = "too_fast"
    EXACT_DUPLICATE_PHOTO = "exact_duplicate_photo"
    CODE_MISSING = "code_missing"
    CODE_WRONG = "code_wrong"


class RecordPositionState(str, Enum):
    PLAUSIBLE = "plausible"
    MISMATCH = "mismatch"
    NOT_CHECKED = "not_checked"
    NOT_GIVEN = "not_given"


def buffer_days(t: ServiceType | str) -> int:
    val = t.value if isinstance(t, ServiceType) else str(t)
    if val in ("super_seeder", "happy_seeder"):
        return 0
    if val in ("baler", "mulcher"):
        return 2
    return 0


def to_x100(acres: float | int | Decimal) -> int:
    """Convert acres to integer hundredths using round-half-up."""
    d = Decimal(str(acres)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(d * 100)


def from_x100(v: int) -> float:
    """Convert integer hundredths back to float acres."""
    return round(v / 100.0, 2)
