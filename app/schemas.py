"""Pydantic v2 schemas for request and response validation (Contract Section 11)."""

import re
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.enums import (
    MachineStatus,
    NotServedReason,
    ServiceType,
)

PHONE_PATTERN = re.compile(r"^[6-9]\d{9}$")


def validate_phone_str(v: str) -> str:
    cleaned = v.strip()
    if not PHONE_PATTERN.match(cleaned):
        raise ValueError("Phone must be 10 digits starting with 6-9.")
    return cleaned


def validate_acres_val(v: float | Decimal) -> float:
    try:
        f = float(v)
    except Exception:
        raise ValueError("Acres must be a valid number.") from None
    if f < 0.25 or f > 200.0:
        raise ValueError("Acres must be between 0.25 and 200.")
    # Check at most 2 decimal places
    d = Decimal(str(f))
    if d.as_tuple().exponent < -2:
        raise ValueError("Acres may have at most 2 decimal places.")
    return f


# --- Request Schemas ---

class FarmerBrief(BaseModel):
    name: str | None = None
    phone: str


class ExplanationBrief(BaseModel):
    reason_code: str | None = None
    reason: str | None = None
    data_used: dict[str, Any] | None = None
    next_action: str | None = None
    nearest_alternative: str | None = None
    alternative_distance_km: float | None = None


class SlotBrief(BaseModel):
    id: int
    machine_id: int
    machine_name: str
    service_date: date
    seq: int
    status: str


class RequestIn(BaseModel):
    phone: str
    name: str | None = None
    village: str
    lat: float | None = None
    lon: float | None = None
    acres: float
    service_type: ServiceType
    harvest_date: date | None = None
    deadline_date: date | None = None
    consent_service: bool
    consent_evidence: bool = True
    consent_share: bool = True

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        return validate_phone_str(v)

    @field_validator("acres")
    @classmethod
    def check_acres(cls, v: float) -> float:
        return validate_acres_val(v)


class RequestPatch(BaseModel):
    name: str | None = None
    village: str | None = None
    lat: float | None = None
    lon: float | None = None
    acres: float | None = None
    service_type: ServiceType | None = None
    harvest_date: date | None = None
    deadline_date: date | None = None

    @field_validator("acres")
    @classmethod
    def check_acres(cls, v: float | None) -> float | None:
        if v is not None:
            return validate_acres_val(v)
        return v


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    source: str
    farmer: FarmerBrief
    village: str
    acres: float
    service_type: str
    harvest_date: date | None = None
    sow_by: date | None = None
    deadline_date: date | None = None
    explanation: ExplanationBrief
    slot: SlotBrief | None = None
    badges: list[str] = []
    created_at: str


# --- Machine Schemas ---

class MachineIn(BaseModel):
    name: str
    type: str
    service_types: list[ServiceType]
    capacity_acres_per_day: float
    implement_width_m: float | None = None
    active_from: date | None = None
    active_to: date | None = None

    @field_validator("capacity_acres_per_day")
    @classmethod
    def check_capacity(cls, v: float) -> float:
        return validate_acres_val(v)


class MachinePatch(BaseModel):
    name: str | None = None
    type: str | None = None
    service_types: list[ServiceType] | None = None
    capacity_acres_per_day: float | None = None
    implement_width_m: float | None = None
    active_from: date | None = None
    active_to: date | None = None
    status: MachineStatus | None = None

    @field_validator("capacity_acres_per_day")
    @classmethod
    def check_capacity(cls, v: float | None) -> float | None:
        if v is not None:
            return validate_acres_val(v)
        return v


class MachineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    service_types: list[str]
    capacity_acres_per_day: float
    status: str
    active_from: date | None = None
    active_to: date | None = None
    driver_path: str
    # Pilot v0.2 (additive)
    driver_link_status: str = "active"  # active | expired | revoked
    driver_link_expires_at: str | None = None


# --- Plot Schemas ---

class PlotIn(BaseModel):
    farmer_phone: str
    village: str
    pin_lat: float | None = None
    pin_lon: float | None = None
    acres: float | None = None
    geojson: str | None = None

    @field_validator("farmer_phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        return validate_phone_str(v)

    @field_validator("acres")
    @classmethod
    def check_acres(cls, v: float | None) -> float | None:
        if v is not None:
            return validate_acres_val(v)
        return v


class PlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    farmer_id: int
    village_name: str
    acres: float
    pin_lat: float | None = None
    pin_lon: float | None = None
    centroid_lat: float | None = None
    centroid_lon: float | None = None
    location_source: str
    geojson: str | None = None
    warning: str | None = None


class NotServedIn(BaseModel):
    reason: NotServedReason
    note: str | None = None


class MessageOpenedIn(BaseModel):
    channel: str  # "wa_link" | "tel"


# --- Slot and Evidence Schemas ---

class LocationBrief(BaseModel):
    lat: float | None = None
    lon: float | None = None
    source: str = "none"


class MachineBrief(BaseModel):
    id: int
    name: str


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    seq: int
    status: str
    service_date: date
    machine: MachineBrief
    request_id: int
    farmer_name: str | None = None
    village: str
    acres: float
    deadline_date: date | None = None
    location: LocationBrief
    est_distance_km: float | None = None
    link_token: str | None = None
    needs_review: bool = False
    flags: list[str] = []
    started_at: str | None = None
    done_at: str | None = None
    record_token: str | None = None


class EvidenceDetail(BaseModel):
    kind: str
    lat: float | None = None
    lon: float | None = None
    accuracy_m: float | None = None
    distance_to_plot_m: float | None = None
    plausible: bool | None = None
    position_state: str = "not_checked"
    photo: str = "present"
    timestamp: str


class SlotEvidenceOut(BaseModel):
    slot_id: int
    status: str
    evidence: EvidenceDetail
    flags: list[str] = []
    needs_review: bool = False
    record_url: str | None = None


class RecordOut(BaseModel):
    request_id: str
    village: str
    machine: str
    acres: float
    service_type: str
    scheduled: str
    deadline_date: str
    started_at: str | None = None
    done_at: str | None = None
    start_position: str = "not_checked"
    done_position: str = "not_checked"
    start_photo: str = "present"
    done_photo: str = "present"
    evidence_note: str | None = None
    farmer_confirmed: bool | None = None
    outcome: str = "COMPLETED"
    on_time: bool
    flags: list[str] = []
    needs_review: bool = False
    badges: list[str] = []
    record_hash: str
    hash_version: str = "v1"
