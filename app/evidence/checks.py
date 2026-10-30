"""Evidence integrity and anomaly checks (Contract Section 9 & Step 07)."""

from datetime import timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.enums import from_x100
from app.event_log import log_event
from app.evidence.rules import (
    code_flags,
    duplicate_photo,
    flags_for_position,
    too_fast,
)
from app.models import Evidence, Request, Slot


def run_checks(session: Session, slot: Slot) -> list[str]:
    """Run all evidence checks at slot completion and log each check to event_log.

    Flags ask a person to look. They never change a status and never block.
    """
    flags: list[str] = []

    req = session.query(Request).filter_by(id=slot.request_id).first()
    evidence_rows = (
        session.query(Evidence)
        .filter_by(slot_id=slot.id)
        .order_by(Evidence.id.asc())
        .all()
    )

    # 1. Position check across this slot's evidence rows
    pos_flagged = False
    for ev in evidence_rows:
        if ev.lat is not None and ev.lon is not None:
            pos_state = (
                "plausible"
                if ev.plausible is True
                else "mismatch"
                if ev.plausible is False
                else "not_checked"
            )
            if flags_for_position(pos_state, ev.plausible):
                pos_flagged = True
    if pos_flagged:
        flags.append("position_mismatch")
    log_event(
        session=session,
        actor="system",
        entity="slot",
        entity_id=slot.id,
        event="check:position",
        payload={"flagged": pos_flagged},
    )

    # 2. Duration check: too_fast
    acres_val = from_x100(req.acres_x100) if req else 0.0
    st_at = slot.started_at
    if st_at is not None and st_at.tzinfo is None:
        st_at = st_at.replace(tzinfo=timezone.utc)
    dn_at = slot.done_at
    if dn_at is not None and dn_at.tzinfo is None:
        dn_at = dn_at.replace(tzinfo=timezone.utc)
    is_too_fast = too_fast(
        started_at=st_at,
        done_at=dn_at,
        acres=acres_val,
        min_per_acre=float(settings.too_fast_min_per_acre),
    )
    if is_too_fast:
        flags.append("too_fast")
    log_event(
        session=session,
        actor="system",
        entity="slot",
        entity_id=slot.id,
        event="check:too_fast",
        payload={"flagged": is_too_fast, "min_per_acre": settings.too_fast_min_per_acre},
    )

    # 3. Exact duplicate photo check against other evidence rows in the database
    is_dup = False
    other_hashes = [
        row[0]
        for row in session.query(Evidence.photo_sha256)
        .filter(Evidence.slot_id != slot.id, Evidence.photo_sha256.isnot(None))
        .all()
    ]
    seen_in_slot: list[str] = []
    for ev in evidence_rows:
        if ev.photo_sha256:
            # Flag if photo matches another job's photo OR if start and done uploaded two different files with identical bytes?
            # Note: In test_smoke.py, TINY_JPEG is uploaded for both start and done of the same slot,
            # while E6 states: "The same file uploaded on two jobs -> Flag exact_duplicate_photo".
            if duplicate_photo(ev.photo_sha256, other_hashes):
                is_dup = True
            seen_in_slot.append(ev.photo_sha256)

    if is_dup:
        flags.append("exact_duplicate_photo")
    log_event(
        session=session,
        actor="system",
        entity="slot",
        entity_id=slot.id,
        event="check:duplicate_photo",
        payload={"flagged": is_dup},
    )

    # 4. Farmer's service code check
    c_flags, confirmed = code_flags(slot.service_code, slot.code_entered)
    if slot.code_entered is None or str(slot.code_entered).strip() == "":
        slot.farmer_confirmed = None
    else:
        slot.farmer_confirmed = confirmed
    flags.extend(c_flags)
    log_event(
        session=session,
        actor="system",
        entity="slot",
        entity_id=slot.id,
        event="check:service_code",
        payload={"flags": c_flags, "farmer_confirmed": slot.farmer_confirmed},
    )

    return flags
