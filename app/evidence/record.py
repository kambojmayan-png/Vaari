"""Service record creation, canonical hashing (v1) and verification."""

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app import clock
from app.models import Evidence, Request, ServiceRecord, Slot
from app.tokens import new_token, record_link_expiry


def canonical_json(payload: dict[str, Any]) -> str:
    """Serialize payload to canonical JSON (sorted keys, compact separators, UTF-8)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(payload: dict[str, Any]) -> str:
    raw = canonical_json(payload).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def build_payload(session: Session, slot: Slot) -> dict[str, Any]:
    """Build the exact v1 record payload from database rows only."""
    req = session.query(Request).filter_by(id=slot.request_id).one()
    evidence_rows = (
        session.query(Evidence)
        .filter_by(slot_id=slot.id)
        .order_by(Evidence.id.asc())
        .all()
    )

    evidence_list = []
    for ev in evidence_rows:
        evidence_list.append({
            "kind": ev.kind,
            "server_time": clock.iso_z(ev.server_time),
            "lat": ev.lat,
            "lon": ev.lon,
            "accuracy_m": ev.accuracy_m,
            "photo_sha256": ev.photo_sha256,
        })

    return {
        "request_id": req.id,
        "slot_id": slot.id,
        "machine_id": slot.machine_id,
        "acres_x100": req.acres_x100,
        "service_date": str(slot.service_date),
        "deadline_date": str(req.deadline_date) if req.deadline_date else None,
        "started_at": clock.iso_z(slot.started_at) if slot.started_at else None,
        "done_at": clock.iso_z(slot.done_at) if slot.done_at else None,
        "code_entered": slot.code_entered,
        "evidence": evidence_list,
    }


def create_record(session: Session, slot: Slot) -> ServiceRecord:
    """Create a tamper-evident ServiceRecord for a completed slot."""
    req = session.query(Request).filter_by(id=slot.request_id).one()
    session.flush()

    payload = build_payload(session, slot)
    record_hash = compute_hash(payload)

    # on_time: IST date of done_at <= deadline_date
    if slot.done_at and req.deadline_date:
        on_time = clock.ist_date(slot.done_at) <= req.deadline_date
    else:
        on_time = True

    token = new_token()
    record = ServiceRecord(
        slot_id=slot.id,
        token=token,
        outcome="COMPLETED",
        on_time=on_time,
        record_hash=record_hash,
        hash_version="v1",
        generated_at=clock.now_utc(),
        token_expires_at=record_link_expiry(),
        token_revoked_at=None,
    )
    session.add(record)
    session.flush()
    return record


def verify(session: Session, token: str) -> dict[str, Any]:
    """Verify stored record hash against recomputed hash from DB rows."""
    record = session.query(ServiceRecord).filter_by(token=token).first()
    if record is None:
        return {"stored": None, "recomputed": None, "match": False}

    slot = session.query(Slot).filter_by(id=record.slot_id).one()
    recomputed = compute_hash(build_payload(session, slot))
    return {
        "stored": record.record_hash,
        "recomputed": recomputed,
        "match": record.record_hash == recomputed,
    }
