"""Structured JSON logs, request IDs and /api/ready (pilot item C9)."""

import io
import json
import logging

import pytest

from app.logging_setup import JsonFormatter, redact
from tests.fixtures.synthetic_photos import TINY_JPEG

SECRET_NAME = "Gurpreet Synthetic Kaur"
SECRET_PHONE = "9876501234"


@pytest.fixture
def captured():
    """Capture every log line as parsed JSON, through the real formatter."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    old = root.level
    root.setLevel(logging.INFO)
    yield buf
    root.removeHandler(handler)
    root.setLevel(old)


def lines(buf):
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


def test_every_response_has_a_request_id(client):
    r = client.get("/api/health")
    assert len(r.headers["x-request-id"]) >= 8
    assert client.get("/api/nope").headers["x-request-id"]


def test_good_incoming_request_id_is_kept_bad_one_replaced(client):
    assert client.get("/api/health", headers={"X-Request-ID": "abc-12345678"}).headers["x-request-id"] == "abc-12345678"
    bad = client.get("/api/health", headers={"X-Request-ID": "x\"; drop"}).headers["x-request-id"]
    assert bad != "x\"; drop" and len(bad) == 32


def test_access_line_is_json_with_route_template_not_path(client, captured):
    client.get("/api/records/SomeRecordTokenValue123", headers={"X-Request-ID": "req-00000001"})
    access = [ln for ln in lines(captured) if ln.get("event") == "request"]
    assert access, captured.getvalue()
    a = access[-1]
    assert a["route"] == "/api/records/{token}"
    assert a["status"] == 404 and a["method"] == "GET" and a["request_id"] == "req-00000001"
    assert "SomeRecordTokenValue123" not in captured.getvalue()
    assert isinstance(a["duration_ms"], (int, float))


def test_no_names_phones_tokens_or_images_in_logs(client, auth_headers, captured):
    # A full job: create a request with a name and phone, schedule, start, done, open the record.
    client.post(
        "/api/machines",
        json={"name": "SS 1", "type": "Super Seeder", "service_types": ["super_seeder"], "capacity_acres_per_day": 8},
        headers=auth_headers,
    )
    from app import clock

    rid = client.post(
        "/api/requests",
        json={
            "phone": SECRET_PHONE, "name": SECRET_NAME, "village": "Pind Kalan", "acres": 2.0,
            "service_type": "super_seeder", "harvest_date": str(clock.today()), "consent_service": True,
            "consent_evidence": True, "consent_share": True,
        },
        headers=auth_headers,
    ).json()["id"]
    req = client.get(f"/api/requests/{rid}", headers=auth_headers).json()
    slot = next(s for s in client.get("/api/slots", headers=auth_headers).json() if s["id"] == req["slot"]["id"])
    h = {"X-Vaari-Slot-Token": slot["link_token"]}
    client.post(f"/api/slots/{slot['id']}/start", headers=h, files={"photo": ("a.jpg", TINY_JPEG, "image/jpeg")})
    done = client.post(f"/api/slots/{slot['id']}/done", headers=h, files={"photo": ("b.jpg", TINY_JPEG, "image/jpeg")})
    record_token = done.json()["record_url"].rsplit("/", 1)[1]
    client.get(f"/api/records/{record_token}")
    client.get(f"/api/slots/{slot['id']}/message", headers=auth_headers)
    client.post("/api/intake/register-photo", headers=auth_headers, files={"photo": ("r.jpg", TINY_JPEG, "image/jpeg")})

    text = captured.getvalue()
    assert text, "expected log lines"
    for secret in (SECRET_NAME, SECRET_PHONE, slot["link_token"], record_token, "Pind Kalan", "test-passcode"):
        assert secret not in text, secret
    assert "\xff\xd8" not in text
    for line in lines(captured):
        assert set(line) <= {"ts", "level", "logger", "msg", "request_id", "event", "method", "route",
                             "status", "duration_ms", "env", "auth", "reader", "revision", "error_type", "where",
                             "provider", "model", "latency_ms", "rows", "ok", "counts", "checks"}


def test_redaction_filter_masks_phones_tokens_and_bearer():
    assert redact("call 9876501234 now") == "call [phone] now"
    assert redact("+91 98765 01234") == "[phone]"
    assert redact("tok AbCdEfGhIjKlMnOpQrStUv end") == "tok [token] end"
    assert redact("Authorization: Bearer v1.abc.def") == "Authorization: Bearer [redacted]"
    assert redact("acres 3.2 on 2026-10-30") == "acres 3.2 on 2026-10-30"
    assert redact("in enforce_startup_checks") == "in enforce_startup_checks"  # 22 chars, not a token


def test_unhandled_error_gives_500_shape_and_logs_type_only(client, captured):
    def boom(*a, **k):
        raise RuntimeError(f"leaky message with {SECRET_PHONE}")

    from app.main import app

    @app.get("/api/test-boom")
    def _boom():
        boom()

    r = client.get("/api/test-boom", headers={"X-Request-ID": "boom-0000001"})
    assert r.status_code == 500
    assert r.json() == {
        "error_code": "INTERNAL_ERROR",
        "message": "Something went wrong on the server. It has been logged.",
        "details": {"request_id": "boom-0000001"},
    }
    assert r.headers["x-content-type-options"] == "nosniff"
    err = [ln for ln in lines(captured) if ln.get("event") == "unhandled_error"]
    assert err and err[0]["error_type"] == "RuntimeError" and err[0]["request_id"] == "boom-0000001"
    assert "test_logging_and_ready.py" in err[0]["where"] or "app/" in err[0]["where"]
    assert SECRET_PHONE not in captured.getvalue() and "leaky" not in captured.getvalue()


def test_ready_when_everything_is_ok(client):
    r = client.get("/api/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["migrations"] == "ok"
    assert body["checks"]["storage"] == "ok"
    assert body["checks"]["reader"] == "mock"


def test_not_ready_when_storage_is_not_writable(client, monkeypatch, tmp_path):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    monkeypatch.setenv("VAARI_DATA_DIR", str(blocker))
    r = client.get("/api/ready")
    assert r.status_code == 503
    assert r.json()["error_code"] == "NOT_READY"
    assert r.json()["details"]["checks"]["storage"] == "error"


def test_not_ready_when_migrations_are_behind(client, temp_db):
    from app.db import get_engine

    with get_engine().begin() as conn:
        conn.exec_driver_sql("UPDATE alembic_version SET version_num='0001'")
    r = client.get("/api/ready")
    assert r.status_code == 503
    assert r.json()["details"]["checks"]["migrations"] == "behind"
