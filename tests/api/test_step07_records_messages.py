"""API tests for Step 07: service records, verify (E10), dashboard and messages (T2)."""

from datetime import date, datetime, timezone
from urllib.parse import unquote

from app import clock
from app.models import Request, Slot
from tests.fixtures.synthetic_photos import TINY_JPEG


def setup_running_slot(client, auth_headers):
    today = clock.today()
    client.post(
        "/api/machines",
        json={
            "name": f"SS-{clock.now_utc().timestamp()}",
            "type": "Super Seeder",
            "service_types": ["super_seeder"],
            "capacity_acres_per_day": 8.0,
        },
        headers=auth_headers,
    )
    r_res = client.post(
        "/api/requests",
        json={
            "phone": "9812345678",
            "name": "Secret Farmer Name",
            "village": "Pind Kalan",
            "acres": 3.2,
            "service_type": "super_seeder",
            "harvest_date": str(today),
            "deadline_date": str(today),
            "consent_service": True,
            "consent_evidence": True,
            "consent_share": True,
        },
        headers=auth_headers,
    )
    client.post("/api/schedule/run", headers=auth_headers)
    req = client.get(f"/api/requests/{r_res.json()['id']}", headers=auth_headers).json()
    slot_id = req["slot"]["id"]

    all_slots = client.get("/api/slots", headers=auth_headers).json()
    slot_data = next(s for s in all_slots if s["id"] == slot_id)
    return slot_id, slot_data["link_token"], req["id"]


def test_service_record_at_done_and_no_personal_data(client, auth_headers):
    """Record created at done; never contains name or phone."""
    slot_id, slot_token, _ = setup_running_slot(client, auth_headers)
    # Start
    client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("start.jpg", TINY_JPEG, "image/jpeg")},
        data={"lat": 30.73, "lon": 76.77},
    )
    # Done
    done_res = client.post(
        f"/api/slots/{slot_id}/done",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("done.jpg", TINY_JPEG, "image/jpeg")},
        data={"lat": 30.73, "lon": 76.77, "service_code": "1234"},
    )
    assert done_res.status_code == 200
    record_url = done_res.json()["record_url"]
    record_token = record_url.split("/")[-1]

    # Fetch record
    rec_res = client.get(f"/api/records/{record_token}")
    assert rec_res.status_code == 200
    rec = rec_res.json()
    assert rec["request_id"].startswith("VR-")
    assert rec["record_hash"].startswith("sha256:")
    assert rec["outcome"] == "COMPLETED"

    # Strict check: NO farmer name or phone in record response
    rec_text = rec_res.text
    assert "9812345678" not in rec_text
    assert "Secret Farmer Name" not in rec_text
    assert "phone" not in rec
    assert "farmer_name" not in rec


def test_T2_on_time_boundary(client, auth_headers, temp_db):
    """Test T2: done_at 2026-10-24T19:00Z, deadline 24 Oct -> on_time is false (IST date is 25 Oct)."""
    slot_id, slot_token, req_id = setup_running_slot(client, auth_headers)
    session = temp_db()

    # Set deadline 24 Oct
    req = session.query(Request).filter_by(id=req_id).one()
    req.deadline_date = date(2026, 10, 24)
    slot = session.query(Slot).filter_by(id=slot_id).one()
    slot.status = "in_progress"
    # Frozen done_at 2026-10-24 19:00 UTC = 2026-10-25 00:30 IST
    slot.started_at = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)
    slot.done_at = datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc)
    session.commit()

    from app.evidence.record import create_record
    rec = create_record(session, slot)
    session.commit()

    assert rec.on_time is False
    session.close()


def test_E10_verify_hash_and_tamper_detection(client, auth_headers, temp_db):
    """Test E10: verify match is true, then false if DB row is modified."""
    slot_id, slot_token, req_id = setup_running_slot(client, auth_headers)
    client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("start.jpg", TINY_JPEG, "image/jpeg")},
    )
    done_res = client.post(
        f"/api/slots/{slot_id}/done",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("done.jpg", TINY_JPEG, "image/jpeg")},
    )
    record_token = done_res.json()["record_url"].split("/")[-1]

    # Verify initial match
    v1 = client.get(f"/api/records/{record_token}/verify").json()
    assert v1["match"] is True
    assert v1["stored"] == v1["recomputed"]

    # Tamper with request acres in database
    session = temp_db()
    r = session.query(Request).filter_by(id=req_id).one()
    r.acres_x100 = 9999  # tampered
    session.commit()
    session.close()

    # Verify recomputed hash does not match stored hash
    v2 = client.get(f"/api/records/{record_token}/verify").json()
    assert v2["match"] is False
    assert v2["stored"] != v2["recomputed"]


def test_dashboard_completed_count_increments_after_done(client, auth_headers):
    """Dashboard completed count moves by one after a done slot."""
    d0 = client.get("/api/dashboard/summary", headers=auth_headers).json()
    comp_before = d0["completed"]

    slot_id, slot_token, _ = setup_running_slot(client, auth_headers)
    client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("start.jpg", TINY_JPEG, "image/jpeg")},
    )
    client.post(
        f"/api/slots/{slot_id}/done",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("done.jpg", TINY_JPEG, "image/jpeg")},
    )

    d1 = client.get("/api/dashboard/summary", headers=auth_headers).json()
    assert d1["completed"] == comp_before + 1


def test_slot_message_and_opened_endpoint(client, auth_headers):
    """Slot message rendering in Punjabi & English and tracking opened."""
    slot_id, _, _ = setup_running_slot(client, auth_headers)

    res = client.get(f"/api/slots/{slot_id}/message", headers=auth_headers)
    assert res.status_code == 200
    msg = res.json()
    assert "body" in msg
    assert "body_en" in msg
    assert msg["service_code"] in msg["body"]
    assert "wa_link" in msg
    assert "tel_link" in msg

    # Verify wa_link decodes back to body
    wa_link = msg["wa_link"]
    query_text = wa_link.split("?text=")[-1]
    decoded_body = unquote(query_text)
    assert decoded_body == msg["body"]

    # Verify opened
    open_res = client.post(
        f"/api/slots/{slot_id}/message/opened",
        json={"channel": "wa_link"},
        headers=auth_headers,
    )
    assert open_res.status_code == 204
