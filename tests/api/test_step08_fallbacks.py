"""Automated fallback tests for Step 08 (Testing Section 8)."""

import time
from datetime import date
from pathlib import Path

from app.config import settings
from app.intake.hosted import HostedVisionReader
from app.intake.reader import ReaderUnavailable
from app.routes import intake as intake_route
from app.seed.seed import reset_db
from tests.fixtures.synthetic_photos import TINY_JPEG

TODAY = date(2026, 10, 25)


class DummyHostedSettings:
    allow_hosted_reader = True
    vision_provider = "gemini"
    vision_model = "gemini-2.5-flash"
    reader_timeout_s = 1


def test_fallback_reader_timeout_gives_503_with_intake_id(client, auth_headers, monkeypatch):
    """Reader timeout -> 503 READER_UNAVAILABLE with details.intake_id, and health shows reader down."""
    def timeout_client(image: bytes, media_type: str, prompt: str, timeout_s: float) -> str:
        raise TimeoutError("Vision API timed out")

    reader = HostedVisionReader(
        settings=DummyHostedSettings(),
        client_callable=timeout_client,
        today_override=TODAY,
    )
    monkeypatch.setattr(intake_route, "get_reader", lambda _s=None: reader)

    res = client.post(
        "/api/intake/register-photo",
        headers=auth_headers,
        files={"photo": ("timeout_page.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert res.status_code == 503
    data = res.json()
    assert data["error_code"] == "READER_UNAVAILABLE"
    assert "Reader unavailable: type the rows" in data["message"]
    assert "intake_id" in data["details"]

    # Health endpoint reports reader == "down"
    health = client.get("/api/health").json()
    assert health["reader"] == "down"

    # Stored photo is still served for the side-by-side manual form
    intake_id = data["details"]["intake_id"]
    img_res = client.get(f"/api/intake/{intake_id}/image", headers=auth_headers)
    assert img_res.status_code == 200

    intake_route.clear_reader_failure()


def test_fallback_reader_malformed_json_twice_gives_503(client, auth_headers, monkeypatch):
    """Malformed JSON twice -> 503 READER_UNAVAILABLE with details.intake_id."""
    calls = []

    def bad_json_client(image: bytes, media_type: str, prompt: str, timeout_s: float) -> str:
        calls.append(prompt)
        return "not-json-{{{"

    reader = HostedVisionReader(
        settings=DummyHostedSettings(),
        client_callable=bad_json_client,
        today_override=TODAY,
    )
    monkeypatch.setattr(intake_route, "get_reader", lambda _s=None: reader)

    res = client.post(
        "/api/intake/register-photo",
        headers=auth_headers,
        files={"photo": ("bad_json.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert len(calls) == 2
    assert res.status_code == 503
    data = res.json()
    assert data["error_code"] == "READER_UNAVAILABLE"
    assert "intake_id" in data["details"]

    intake_route.clear_reader_failure()


def test_fallback_reader_empty_page_gives_503(client, auth_headers, monkeypatch):
    """Empty rows returned by model -> 503 READER_UNAVAILABLE."""
    class EmptyPageReader:
        def read(self, image: bytes, media_type: str = "image/jpeg"):
            raise ReaderUnavailable("No readable rows found on register page.")

    monkeypatch.setattr(intake_route, "get_reader", lambda _s=None: EmptyPageReader())

    res = client.post(
        "/api/intake/register-photo",
        headers=auth_headers,
        files={"photo": ("blank_page.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert res.status_code == 503
    assert res.json()["error_code"] == "READER_UNAVAILABLE"
    assert "intake_id" in res.json()["details"]

    intake_route.clear_reader_failure()


def test_fallback_location_permission_denied_closes_job_with_self_reported_badge(
    client, auth_headers
):
    """When location permission is denied (no lat/lon sent), job closes and record is badged 'position self-reported'."""
    reset_db()
    slots = client.get("/api/slots", headers=auth_headers).json()
    demo_slot = next(s for s in slots if s["request_id"] == 1)
    slot_id = demo_slot["id"]
    slot_token = demo_slot["link_token"]

    # Start without lat/lon
    s_res = client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("start_no_gps.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert s_res.status_code == 200
    assert s_res.json()["evidence"]["position_state"] == "not_given"

    # Done without lat/lon
    d_res = client.post(
        f"/api/slots/{slot_id}/done",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("done_no_gps.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert d_res.status_code == 200
    record_token = d_res.json()["record_url"].split("/")[-1]

    rec = client.get(f"/api/records/{record_token}").json()
    assert rec["start_position"] == "not_given"
    assert rec["done_position"] == "not_given"
    assert "position self-reported" in rec["badges"]


def test_fallback_deleted_database_rebuilds_under_one_minute(temp_db):
    """Deleting the database file and running reset rebuilds the full demo in under 60 seconds."""
    db_file = Path(settings.db_path)
    if db_file.exists():
        try:
            db_file.unlink()
        except Exception:
            pass

    t0 = time.perf_counter()
    counts = reset_db()
    elapsed = time.perf_counter() - t0

    assert elapsed < 60.0, f"Reset took {elapsed:.2f}s (limit is 60s)"
    assert counts["scheduled"] == 28
    assert counts["will_miss"] == 7
    assert counts["needs_info"] == 5
