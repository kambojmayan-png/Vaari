"""API tests for Step 05: intake upload, stored draft, confirmation, and purge-images."""

from datetime import timedelta
from pathlib import Path

from app import clock
from app.intake.reader import ReaderUnavailable
from app.models import IntakePage, RegisterDraft, Request
from app.routes import intake as intake_route
from tests.fixtures.synthetic_photos import TINY_JPEG


def test_upload_with_mock_reader_stores_draft_and_creates_no_requests(client, auth_headers, temp_db):
    res = client.post(
        "/api/intake/register-photo",
        headers=auth_headers,
        files={"photo": ("page1.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert res.status_code == 200
    data = res.json()
    intake_id = data["intake_id"]
    assert data["reader"] == "mock"
    assert data["status"] == "drafted"
    assert len(data["rows"]) == 6

    # Draft survives and can be retrieved via GET /api/intake/{id}
    get_res = client.get(f"/api/intake/{intake_id}", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["intake_id"] == intake_id

    # Image is retrievable via GET /api/intake/{id}/image
    img_res = client.get(f"/api/intake/{intake_id}/image", headers=auth_headers)
    assert img_res.status_code == 200
    assert img_res.content.startswith(b"\xff\xd8\xff")

    # Rule: No request exists before confirmation
    session = temp_db()
    assert session.query(Request).count() == 0
    session.close()


def test_confirm_creates_requests_tracks_edits_skips_and_refuses_second_confirm(
    client, auth_headers, temp_db
):
    res = client.post(
        "/api/intake/register-photo",
        headers=auth_headers,
        files={"photo": ("page1.jpg", TINY_JPEG, "image/jpeg")},
    )
    intake_id = res.json()["intake_id"]
    rows = res.json()["rows"]

    # Prepare confirmation payload:
    # - Row 1: confirm as-is
    # - Row 2: edit acres from 3.0 to 3.5
    # - Row 3: skip (had 7-digit phone)
    # - Rows 4, 5, 6: skip for this test
    confirm_rows = [
        {"row": 1, "fields": rows[0]["fields"], "skip": False},
        {
            "row": 2,
            "fields": {**rows[1]["fields"], "acres": 3.5},
            "skip": False,
        },
        {"row": 3, "fields": rows[2]["fields"], "skip": True},
        {"row": 4, "fields": rows[3]["fields"], "skip": True},
        {"row": 5, "fields": rows[4]["fields"], "skip": True},
        {"row": 6, "fields": rows[5]["fields"], "skip": True},
    ]

    c_res = client.post(
        f"/api/intake/{intake_id}/confirm",
        headers=auth_headers,
        json={"rows": confirm_rows},
    )
    assert c_res.status_code == 201
    c_data = c_res.json()
    assert len(c_data["created_request_ids"]) == 2
    assert c_data["skipped_rows"] == [3, 4, 5, 6]
    assert c_data["errors"] == []

    # Verify created requests have source == "register"
    for req_id in c_data["created_request_ids"]:
        r_out = client.get(f"/api/requests/{req_id}", headers=auth_headers).json()
        assert r_out["source"] == "register"

    # Verify edited cell is saved as edited in register_draft
    session = temp_db()
    draft2 = (
        session.query(RegisterDraft)
        .filter_by(intake_page_id=intake_id, row_no=2)
        .one()
    )
    assert draft2.edited is True
    assert draft2.edited_fields_json.get("acres") == 3.5
    assert draft2.confirmed_at is not None
    session.close()

    # Confirming a second time gives 404 DRAFT_NOT_FOUND
    c_res2 = client.post(
        f"/api/intake/{intake_id}/confirm",
        headers=auth_headers,
        json={"rows": confirm_rows},
    )
    assert c_res2.status_code == 404
    assert c_res2.json()["error_code"] == "DRAFT_NOT_FOUND"

    # GET /api/intake/{id} after confirmation also returns 404 DRAFT_NOT_FOUND
    get_after = client.get(f"/api/intake/{intake_id}", headers=auth_headers)
    assert get_after.status_code == 404
    assert get_after.json()["error_code"] == "DRAFT_NOT_FOUND"


def test_confirm_row_with_7_digit_phone_is_refused_naming_field(client, auth_headers):
    res = client.post(
        "/api/intake/register-photo",
        headers=auth_headers,
        files={"photo": ("page1.jpg", TINY_JPEG, "image/jpeg")},
    )
    intake_id = res.json()["intake_id"]
    rows = res.json()["rows"]

    # Row 3 has 7-digit phone "9000000" -> do not skip it
    confirm_rows = [
        {"row": 1, "fields": rows[0]["fields"], "skip": False},
        {"row": 3, "fields": rows[2]["fields"], "skip": False},
    ]
    c_res = client.post(
        f"/api/intake/{intake_id}/confirm",
        headers=auth_headers,
        json={"rows": confirm_rows},
    )
    assert c_res.status_code == 201
    c_data = c_res.json()
    assert len(c_data["created_request_ids"]) == 1
    assert len(c_data["errors"]) == 1
    assert c_data["errors"][0]["row"] == 3
    assert c_data["errors"][0]["field"] == "phone"


def test_reader_failure_returns_503_with_intake_id_and_image_is_retrievable(
    client, auth_headers, monkeypatch
):
    class FailingReader:
        def read(self, image: bytes, media_type: str = "image/jpeg"):
            raise ReaderUnavailable("Simulated vision provider timeout")

    monkeypatch.setattr(intake_route, "get_reader", lambda _settings=None: FailingReader())

    res = client.post(
        "/api/intake/register-photo",
        headers=auth_headers,
        files={"photo": ("page_fail.jpg", TINY_JPEG, "image/jpeg")},
    )
    assert res.status_code == 503
    err = res.json()
    assert err["error_code"] == "READER_UNAVAILABLE"
    assert "intake_id" in err["details"]
    intake_id = err["details"]["intake_id"]

    # Health endpoint now reports reader == "down" within 5 minutes of failure
    health = client.get("/api/health").json()
    assert health["reader"] == "down"

    # Stored image is still retrievable so the client can show it beside the manual form
    img_res = client.get(f"/api/intake/{intake_id}/image", headers=auth_headers)
    assert img_res.status_code == 200
    assert img_res.content.startswith(b"\xff\xd8\xff")

    intake_route.clear_reader_failure()


def test_purge_expired_register_images(client, auth_headers, temp_db):
    res = client.post(
        "/api/intake/register-photo",
        headers=auth_headers,
        files={"photo": ("page_purge.jpg", TINY_JPEG, "image/jpeg")},
    )
    intake_id = res.json()["intake_id"]

    session = temp_db()
    page = session.query(IntakePage).filter_by(id=intake_id).one()
    page.image_delete_after = clock.now_utc() - timedelta(days=1)
    session.commit()

    # Dry run does not delete file
    dry_deleted = intake_route.purge_expired_register_images(session, dry_run=True)
    assert len(dry_deleted) == 1
    assert Path(dry_deleted[0]).exists()

    # Real purge deletes file
    real_deleted = intake_route.purge_expired_register_images(session, dry_run=False)
    assert len(real_deleted) == 1
    assert not Path(real_deleted[0]).exists()
    session.close()


def test_intake_out_names_the_reader_and_third_party(client, auth_headers):
    """Part 5: IntakeOut says which reader made the draft and whether it is a third party."""
    res = client.post(
        "/api/intake/register-photo",
        headers=auth_headers,
        files={"photo": ("page.jpg", TINY_JPEG, "image/jpeg")},
    )
    body = res.json()
    assert body["reader"] == "mock"
    assert body["reader_name"] == "mock" and body["third_party"] is False
