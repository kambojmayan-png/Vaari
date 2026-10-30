"""Per-user accounts, roles and signed expiring sessions (pilot item A2)."""

import io
from datetime import timedelta

import pytest

from app import clock
from app.auth import secrets_equal
from app.cli_users import create_user, disable_user, list_users
from app.cli_users import main as users_main
from app.models import EventLog, UserAccount

PW_OP = "operator-password-123"
PW_OFF = "officer-password-456"


@pytest.fixture
def users(client):
    create_user("Asha", "operator", PW_OP)
    create_user("ravi", "officer", PW_OFF)
    return client


def login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def bearer(client, username, password):
    r = login(client, username, password)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def new_request_body(phone="9000000999"):
    return {
        "phone": phone, "name": "Test Farmer", "village": "Pind Kalan", "acres": 2.0,
        "service_type": "super_seeder", "harvest_date": clock.today().isoformat(),
        "consent_service": True, "consent_evidence": False, "consent_share": False,
    }


def test_password_is_stored_as_argon2id_hash(users, temp_db):
    with temp_db() as s:
        u = s.query(UserAccount).filter_by(username="asha").one()
        assert u.password_hash.startswith("$argon2id$")
        assert PW_OP not in u.password_hash


def test_short_password_refused(client):
    with pytest.raises(ValueError):
        create_user("short", "operator", "too-short")


def test_unknown_role_refused(client):
    with pytest.raises(ValueError):
        create_user("boss", "admin", "a-long-enough-password")


def test_duplicate_username_refused(users):
    with pytest.raises(ValueError):
        create_user("ASHA", "officer", "another-long-password")


def test_login_returns_token_and_user(users):
    r = login(users, "  ASHA ", PW_OP)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["user"] == {"username": "asha", "role": "operator"}
    assert body["expires_at"].endswith("Z")


@pytest.mark.parametrize("username,password", [("asha", "wrong-password-1"), ("nobody", PW_OP)])
def test_bad_login_gives_same_401(users, username, password):
    r = login(users, username, password)
    assert r.status_code == 401
    assert r.json()["error_code"] == "UNAUTHORIZED"
    assert r.json()["message"] == "Wrong username or password."


def test_me_reports_role(users):
    h = bearer(users, "ravi", PW_OFF)
    r = users.get("/api/auth/me", headers=h)
    assert r.status_code == 200
    assert r.json() == {"username": "ravi", "roles": ["officer"], "via": "session"}


def test_operator_can_create_requests_and_officer_cannot(users):
    op = bearer(users, "asha", PW_OP)
    off = bearer(users, "ravi", PW_OFF)
    assert users.post("/api/requests", json=new_request_body(), headers=op).status_code == 201
    r = users.post("/api/requests", json=new_request_body("9000000998"), headers=off)
    assert r.status_code == 403
    assert r.json()["error_code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    "path",
    ["/api/requests", "/api/schedule", "/api/slots", "/api/plots", "/api/intake/1"],
)
def test_officer_cannot_open_operator_routes(users, path):
    off = bearer(users, "ravi", PW_OFF)
    r = users.get(path, headers=off)
    assert r.status_code in (401, 403), (path, r.status_code)


@pytest.mark.parametrize(
    "path", ["/api/dashboard/summary", "/api/dashboard/usage.csv", "/api/schedule/will-miss", "/api/machines"]
)
def test_officer_can_open_oversight_routes(users, path):
    off = bearer(users, "ravi", PW_OFF)
    assert users.get(path, headers=off).status_code == 200


def test_officer_sees_machines_without_driver_links(users):
    op = bearer(users, "asha", PW_OP)
    users.post(
        "/api/machines",
        json={"name": "SS 9", "type": "Super Seeder", "service_types": ["super_seeder"], "capacity_acres_per_day": 8},
        headers=op,
    )
    off = bearer(users, "ravi", PW_OFF)
    officer_view = users.get("/api/machines", headers=off).json()
    operator_view = users.get("/api/machines", headers=op).json()
    assert officer_view[0]["driver_path"] == ""
    assert operator_view[0]["driver_path"].startswith("/driver/")


def test_every_protected_route_requires_auth(users):
    # Walk the live route table: every non-public /api route must answer 401 with no credentials.
    from app.main import app

    public_prefixes = ("/api/health", "/api/ready", "/api/auth/login", "/api/auth/logout", "/api/driver/", "/api/records/", "/api/test-")
    checked = 0
    for path, ops in app.openapi()["paths"].items():
        if not path.startswith("/api/") or path.startswith(public_prefixes):
            continue
        for method in sorted(m.upper() for m in ops):
            url = path.replace("{id}", "1").replace("{token}", "x").replace("{machine_token}", "x")
            r = users.request(method, url)
            assert r.status_code == 401, (method, url, r.status_code)
            checked += 1
    assert checked >= 20


def test_session_expires(users, monkeypatch):
    h = bearer(users, "asha", PW_OP)
    assert users.get("/api/auth/me", headers=h).status_code == 200
    later = clock.now_utc() + timedelta(hours=13)
    monkeypatch.setattr(clock, "now_utc", lambda: later)
    assert users.get("/api/auth/me", headers=h).status_code == 401


def test_tampered_or_garbage_token_rejected(users):
    h = bearer(users, "asha", PW_OP)
    token = h["Authorization"].split(" ", 1)[1]
    v, sid, exp, sig = token.split(".")
    longer = f"{v}.{sid}.{int(exp) + 86400}.{sig}"
    for bad in (longer, token[:-2] + "xx", "garbage", "v1.a.b.c"):
        r = users.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401, bad


def test_token_signed_with_another_secret_rejected(users, monkeypatch):
    monkeypatch.setenv("VAARI_SECRET_KEY", "first-secret-" + "x" * 32)
    h = bearer(users, "asha", PW_OP)
    monkeypatch.setenv("VAARI_SECRET_KEY", "second-secret-" + "y" * 32)
    assert users.get("/api/auth/me", headers=h).status_code == 401


def test_logout_revokes_session(users):
    h = bearer(users, "asha", PW_OP)
    assert users.post("/api/auth/logout", headers=h).status_code == 204
    assert users.get("/api/auth/me", headers=h).status_code == 401


def test_disable_user_signs_out_and_blocks_login(users):
    h = bearer(users, "asha", PW_OP)
    assert disable_user("asha") == 1
    assert users.get("/api/auth/me", headers=h).status_code == 401
    assert login(users, "asha", PW_OP).status_code == 401
    assert ("asha", "operator", False) in list_users()


def test_event_log_names_the_account(users, temp_db):
    op = bearer(users, "asha", PW_OP)
    rid = users.post("/api/requests", json=new_request_body(), headers=op).json()["id"]
    with temp_db() as s:
        actors = {e.actor for e in s.query(EventLog).filter_by(entity="request", entity_id=rid).all()}
    assert "operator:asha" in actors


def test_passcode_works_in_development(users, auth_headers):
    assert users.get("/api/requests", headers=auth_headers).status_code == 200


def test_passcode_rejected_in_production(users, auth_headers, monkeypatch):
    monkeypatch.setenv("VAARI_ENV", "production")
    r = users.get("/api/requests", headers=auth_headers)
    assert r.status_code == 401
    op = bearer(users, "asha", PW_OP)
    assert users.get("/api/requests", headers=op).status_code == 200
    assert users.get("/api/health").json()["auth"] == "accounts"


def test_operator_session_can_act_on_slot_and_officer_cannot(users, auth_headers):
    users.post(
        "/api/machines",
        json={"name": "SS 9", "type": "Super Seeder", "service_types": ["super_seeder"], "capacity_acres_per_day": 8},
        headers=auth_headers,
    )
    users.post("/api/requests", json=new_request_body(), headers=auth_headers)
    slots = users.get("/api/slots", headers=auth_headers).json()
    target = next(s for s in slots if s["status"] == "scheduled")
    off = bearer(users, "ravi", PW_OFF)
    assert users.post(f"/api/slots/{target['id']}/not-served", json={"reason": "WEATHER"}, headers=off).status_code == 401
    op = bearer(users, "asha", PW_OP)
    r = users.post(f"/api/slots/{target['id']}/not-served", json={"reason": "WEATHER"}, headers=op)
    assert r.status_code == 200


def test_secrets_equal_is_strict():
    assert secrets_equal("abc", "abc")
    assert not secrets_equal("abc", "abd")
    assert not secrets_equal("", "")
    assert not secrets_equal(None, "x")


def test_create_user_command_reads_password_from_stdin(client, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("a-password-from-stdin\n"))
    assert users_main(["create-user", "--username", "meena", "--role", "officer", "--password-stdin"]) == 0
    assert "Created officer 'meena'" in capsys.readouterr().out
    assert login(client, "meena", "a-password-from-stdin").status_code == 200
