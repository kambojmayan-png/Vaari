"""Rate limiting and lockout on sign-in and upload endpoints (pilot item A3)."""

import pytest

from app import clock
from app.cli_users import create_user
from tests.fixtures.synthetic_photos import TINY_JPEG

PW = "operator-password-123"


@pytest.fixture
def fake_clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(clock, "monotonic", lambda: now[0])
    return now


def login(client, username, password, ip_header=None):
    headers = {"X-Forwarded-For": ip_header} if ip_header else {}
    return client.post("/api/auth/login", json={"username": username, "password": password}, headers=headers)


def test_login_rate_limit_per_address(client, fake_clock, monkeypatch):
    monkeypatch.setenv("VAARI_LOGIN_RATE_PER_MIN", "3")
    for i in range(3):
        assert login(client, f"user{i}", "whatever-password").status_code == 401
    r = login(client, "user9", "whatever-password")
    assert r.status_code == 429
    assert r.json()["error_code"] == "RATE_LIMITED"
    assert int(r.headers["retry-after"]) >= 1
    fake_clock[0] += 61
    assert login(client, "user9", "whatever-password").status_code == 401


def test_lockout_after_repeated_wrong_passwords(client, fake_clock):
    create_user("asha", "operator", PW)
    for _ in range(5):
        assert login(client, "asha", "wrong-password-xx").status_code == 401
    fake_clock[0] += 61  # past the per-address window, so only the lockout applies
    r = login(client, "asha", PW)  # right password, still locked
    assert r.status_code == 429
    assert r.json()["error_code"] == "RATE_LIMITED"
    assert r.headers["retry-after"]
    fake_clock[0] += 15 * 60 + 1
    assert login(client, "asha", PW).status_code == 200


def test_lockout_answers_the_same_for_unknown_usernames(client, fake_clock):
    for _ in range(5):
        login(client, "ghost", "wrong-password-xx")
    fake_clock[0] += 61
    r = login(client, "ghost", "wrong-password-xx")
    assert r.status_code == 429
    assert r.json()["message"] == "Too many wrong passwords for this username. Try again later."


def test_success_resets_failure_count(client, fake_clock):
    create_user("asha", "operator", PW)
    for _ in range(4):
        login(client, "asha", "wrong-password-xx")
    assert login(client, "asha", PW).status_code == 200
    fake_clock[0] += 61
    for _ in range(4):
        assert login(client, "asha", "wrong-password-xx").status_code == 401
    fake_clock[0] += 61
    assert login(client, "asha", PW).status_code == 200


def test_lockout_is_logged_for_real_accounts(client, fake_clock, temp_db):
    from app.models import EventLog

    create_user("asha", "operator", PW)
    for _ in range(5):
        login(client, "asha", "wrong-password-xx")
    with temp_db() as s:
        assert s.query(EventLog).filter_by(entity="user_account", event="login_locked").count() == 1


def test_upload_rate_limit_is_checked_before_the_body_is_read(client, auth_headers, fake_clock, monkeypatch):
    monkeypatch.setenv("VAARI_UPLOAD_RATE_PER_MIN", "2")
    files = {"photo": ("page.jpg", TINY_JPEG, "image/jpeg")}
    codes = [
        client.post("/api/intake/register-photo", files=files, headers=auth_headers).status_code
        for _ in range(3)
    ]
    assert codes[:2] == [200, 200]
    assert codes[2] == 429
    # Slot uploads share the same per-address upload budget.
    r = client.post("/api/slots/1/start", headers={"X-Vaari-Slot-Token": "x"})
    assert r.status_code == 429


def test_forwarded_for_is_ignored_unless_trusted(client, fake_clock, monkeypatch):
    monkeypatch.setenv("VAARI_LOGIN_RATE_PER_MIN", "1")
    assert login(client, "a", "whatever-password", ip_header="10.0.0.1").status_code == 401
    # Without VAARI_TRUST_PROXY a different X-Forwarded-For does not get a new budget.
    assert login(client, "b", "whatever-password", ip_header="10.0.0.2").status_code == 429
    monkeypatch.setenv("VAARI_TRUST_PROXY", "true")
    assert login(client, "c", "whatever-password", ip_header="10.0.0.3").status_code == 401


def test_other_routes_are_not_limited(client, auth_headers, fake_clock, monkeypatch):
    monkeypatch.setenv("VAARI_UPLOAD_RATE_PER_MIN", "1")
    monkeypatch.setenv("VAARI_LOGIN_RATE_PER_MIN", "1")
    for _ in range(5):
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/requests", headers=auth_headers).status_code == 200
