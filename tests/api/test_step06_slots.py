"""Tests for Step 06: slot state machine, evidence capture and photos (S1-S10)."""

import hashlib
from pathlib import Path

from app import clock
from app.models import Evidence, ServiceRecord
from tests.fixtures.synthetic_photos import TINY_JPEG


def create_slot_helper(client, auth_headers, consent_evidence=True):
    today = clock.today()
    # Machine
    m_res = client.post(
        "/api/machines",
        json={
            "name": f"Machine-{clock.now_utc().timestamp()}",
            "type": "Super Seeder",
            "service_types": ["super_seeder"],
            "capacity_acres_per_day": 8.0,
        },
        headers=auth_headers,
    )
    machine = m_res.json()

    # Request
    r_res = client.post(
        "/api/requests",
        json={
            "phone": f"98{int(clock.now_utc().timestamp() * 100) % 100000000:08d}",
            "village": "Pind Kalan",
            "acres": 3.0,
            "service_type": "super_seeder",
            "harvest_date": str(today),
            "deadline_date": str(today),
            "consent_service": True,
            "consent_evidence": consent_evidence,
            "consent_share": True,
        },
        headers=auth_headers,
    )
    client.post("/api/schedule/run", headers=auth_headers)
    req = client.get(f"/api/requests/{r_res.json()['id']}", headers=auth_headers).json()
    slot_id = req["slot"]["id"]

    # Fetch slot to get its link_token
    all_slots = client.get("/api/slots", headers=auth_headers).json()
    slot_data = next(s for s in all_slots if s["id"] == slot_id)
    return slot_id, slot_data["link_token"], machine


def test_S1_done_before_start_gives_invalid_transition(client, auth_headers):
    """S1: scheduled -> done -> 409 INVALID_TRANSITION."""
    slot_id, slot_token, _ = create_slot_helper(client, auth_headers)
    res = client.post(
        f"/api/slots/{slot_id}/done",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert res.status_code == 409
    assert res.json()["error_code"] == "INVALID_TRANSITION"


def test_S2_duplicate_start_gives_duplicate_start(client, auth_headers):
    """S2: in_progress -> start -> 409 DUPLICATE_START."""
    slot_id, slot_token, _ = create_slot_helper(client, auth_headers)
    # Start once
    res1 = client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert res1.status_code == 200

    # Start again
    res2 = client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert res2.status_code == 409
    assert res2.json()["error_code"] == "DUPLICATE_START"


def test_S3_start_with_wrong_slot_token_gives_wrong_slot(client, auth_headers):
    """S3: start with another slot's token -> 403 WRONG_SLOT."""
    slot_id1, _, _ = create_slot_helper(client, auth_headers)
    _, slot_token2, _ = create_slot_helper(client, auth_headers)

    res = client.post(
        f"/api/slots/{slot_id1}/start",
        headers={"X-Vaari-Slot-Token": slot_token2},
        files={"photo": ("photo.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert res.status_code == 403
    assert res.json()["error_code"] == "WRONG_SLOT"


def test_S4_start_without_photo_when_consent_given_gives_evidence_missing(client, auth_headers):
    """S4: farmer gave evidence consent, start with no photo -> 422 EVIDENCE_MISSING."""
    slot_id, slot_token, _ = create_slot_helper(client, auth_headers, consent_evidence=True)
    res = client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
    )
    assert res.status_code == 422
    assert res.json()["error_code"] == "EVIDENCE_MISSING"


def test_S4b_start_without_photo_when_consent_refused_succeeds(client, auth_headers):
    """S4b: farmer refused evidence consent, start with no photo -> 200."""
    slot_id, slot_token, _ = create_slot_helper(client, auth_headers, consent_evidence=False)
    res = client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "in_progress"


def test_S5_start_with_photo_and_no_position_gives_not_given(client, auth_headers):
    """S5: start with photo and no position -> 200, position_state 'not_given'."""
    slot_id, slot_token, _ = create_slot_helper(client, auth_headers)
    res = client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert res.status_code == 200
    assert res.json()["evidence"]["position_state"] == "not_given"


def test_S6_done_with_photo_creates_record(client, auth_headers, temp_db):
    """S6: in_progress -> done with photo -> 200, service record created."""
    slot_id, slot_token, _ = create_slot_helper(client, auth_headers)
    # Start
    client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", TINY_JPEG, "image/jpeg")},
        data={"lat": 30.73, "lon": 76.77},
    )
    # Done
    res = client.post(
        f"/api/slots/{slot_id}/done",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", TINY_JPEG, "image/jpeg")},
        data={"lat": 30.73, "lon": 76.77, "service_code": "1234"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "done"
    assert data["record_url"] is not None

    session = temp_db()
    rec = session.query(ServiceRecord).filter_by(slot_id=slot_id).first()
    assert rec is not None
    assert rec.record_hash.startswith("sha256:")
    session.close()


def test_S7_not_served_from_scheduled_reschedules(client, auth_headers):
    """S7: scheduled -> not-served -> request back to open and rescheduled."""
    slot_id, slot_token, _ = create_slot_helper(client, auth_headers)
    res = client.post(
        f"/api/slots/{slot_id}/not-served",
        headers={"X-Vaari-Slot-Token": slot_token},
        json={"reason": "FIELD_NOT_READY", "note": "Too wet"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "not_served"


def test_S8_done_slot_cannot_transition_again(client, auth_headers):
    """S8: done -> any transition -> 409 INVALID_TRANSITION."""
    slot_id, slot_token, _ = create_slot_helper(client, auth_headers)
    client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", TINY_JPEG, "image/jpeg")},
    )
    client.post(
        f"/api/slots/{slot_id}/done",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", TINY_JPEG, "image/jpeg")},
    )
    # Attempt start again
    res1 = client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert res1.status_code == 409
    assert res1.json()["error_code"] == "INVALID_TRANSITION"

    # Attempt done again
    res2 = client.post(
        f"/api/slots/{slot_id}/done",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert res2.status_code == 409
    assert res2.json()["error_code"] == "INVALID_TRANSITION"


def test_S10_not_served_from_in_progress(client, auth_headers):
    """S10: in_progress -> not-served with MACHINE_BROKEN."""
    slot_id, slot_token, _ = create_slot_helper(client, auth_headers)
    client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", TINY_JPEG, "image/jpeg")},
    )
    res = client.post(
        f"/api/slots/{slot_id}/not-served",
        headers={"X-Vaari-Slot-Token": slot_token},
        json={"reason": "MACHINE_BROKEN", "note": "Tractor breakdown"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "not_served"


def test_photo_size_limit_9mb_gives_413(client, auth_headers):
    """9 MB upload exceeds 8 MB limit -> 413 PAYLOAD_TOO_LARGE."""
    slot_id, slot_token, _ = create_slot_helper(client, auth_headers)
    oversized = b"\xff\xd8\xff" + b"0" * (9 * 1024 * 1024)
    res = client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", oversized, "image/jpeg")},
    )
    assert res.status_code == 413
    assert res.json()["error_code"] == "PAYLOAD_TOO_LARGE"


def test_text_file_renamed_jpg_gives_422(client, auth_headers):
    """Text file renamed .jpg fails magic bytes check -> 422 VALIDATION_ERROR on field photo."""
    slot_id, slot_token, _ = create_slot_helper(client, auth_headers)
    fake_image = b"Hello world, I am just plain text masquerading as an image."
    res = client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", fake_image, "image/jpeg")},
    )
    assert res.status_code == 422
    err = res.json()
    assert err["error_code"] == "VALIDATION_ERROR"
    assert err["details"]["field"] == "photo"


def test_saved_photo_on_disk_hash_matches(client, auth_headers, temp_db):
    """Uploaded photo is saved to disk and its content hash matches."""
    slot_id, slot_token, _ = create_slot_helper(client, auth_headers)
    res = client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("photo.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert res.status_code == 200

    session = temp_db()
    ev = session.query(Evidence).filter_by(slot_id=slot_id, kind="start").first()
    assert ev is not None
    assert ev.photo_path is not None
    saved_path = Path(ev.photo_path)
    assert saved_path.exists()
    file_bytes = saved_path.read_bytes()
    assert hashlib.sha256(file_bytes).hexdigest() == ev.photo_sha256
    session.close()
