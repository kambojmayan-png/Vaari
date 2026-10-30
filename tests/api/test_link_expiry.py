"""Expiry and revocation of driver and record links (pilot item A4)."""

from datetime import timedelta

from app import clock
from app.models import Machine
from tests.api.test_step07_records_messages import setup_running_slot
from tests.fixtures.synthetic_photos import TINY_JPEG


def _machine(client, auth_headers):
    return client.get("/api/machines", headers=auth_headers).json()[0]


def _token(machine_out):
    return machine_out["driver_path"].rsplit("/", 1)[1]


def _finish(client, slot_id, slot_token):
    h = {"X-Vaari-Slot-Token": slot_token}
    client.post(f"/api/slots/{slot_id}/start", headers=h, files={"photo": ("s.jpg", TINY_JPEG, "image/jpeg")})
    r = client.post(f"/api/slots/{slot_id}/done", headers=h, files={"photo": ("d.jpg", TINY_JPEG + b"x", "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()["record_url"].rsplit("/", 1)[1]


def later(monkeypatch, days):
    t = clock.now_utc() + timedelta(days=days)
    monkeypatch.setattr(clock, "now_utc", lambda: t)


def test_new_machine_link_has_an_expiry(client, auth_headers):
    setup_running_slot(client, auth_headers)
    m = _machine(client, auth_headers)
    assert m["driver_link_status"] == "active"
    assert m["driver_link_expires_at"].endswith("Z")


def test_driver_link_expires(client, auth_headers, monkeypatch):
    setup_running_slot(client, auth_headers)
    token = _token(_machine(client, auth_headers))
    assert client.get(f"/api/driver/{token}").status_code == 200
    later(monkeypatch, 31)
    r = client.get(f"/api/driver/{token}")
    assert r.status_code == 410
    assert r.json()["error_code"] == "LINK_EXPIRED"
    assert r.json()["details"]["reason"] == "expired"
    assert client.get("/api/slots", headers={"X-Vaari-Machine-Token": token}).status_code == 410


def test_expired_driver_link_also_stops_slot_actions(client, auth_headers, monkeypatch):
    slot_id, slot_token, _ = setup_running_slot(client, auth_headers)
    later(monkeypatch, 31)
    r = client.post(f"/api/slots/{slot_id}/not-served", json={"reason": "WEATHER"}, headers={"X-Vaari-Slot-Token": slot_token})
    assert r.status_code == 410
    # The operator can still act on the slot.
    r = client.post(f"/api/slots/{slot_id}/not-served", json={"reason": "WEATHER"}, headers=auth_headers)
    assert r.status_code == 200


def test_revoke_driver_link(client, auth_headers):
    slot_id, slot_token, _ = setup_running_slot(client, auth_headers)
    m = _machine(client, auth_headers)
    token = _token(m)
    r = client.post(f"/api/machines/{m['id']}/link/revoke", headers=auth_headers)
    assert r.status_code == 200 and r.json()["driver_link_status"] == "revoked"
    r = client.get(f"/api/driver/{token}")
    assert r.status_code == 410 and r.json()["details"]["reason"] == "revoked"
    r = client.post(f"/api/slots/{slot_id}/start", headers={"X-Vaari-Slot-Token": slot_token})
    assert r.status_code == 410


def test_rotate_driver_link_replaces_machine_and_slot_tokens(client, auth_headers):
    slot_id, old_slot_token, _ = setup_running_slot(client, auth_headers)
    m = _machine(client, auth_headers)
    old = _token(m)
    client.post(f"/api/machines/{m['id']}/link/revoke", headers=auth_headers)
    r = client.post(f"/api/machines/{m['id']}/link/rotate", headers=auth_headers)
    assert r.status_code == 200
    new = _token(r.json())
    assert new != old and r.json()["driver_link_status"] == "active"
    assert client.get(f"/api/driver/{old}").status_code == 404
    view = client.get(f"/api/driver/{new}", params={"date": str(clock.today())})
    assert view.status_code == 200
    new_slot_token = next(s["link_token"] for s in view.json()["slots"] if s["id"] == slot_id)
    assert new_slot_token != old_slot_token
    # A phone still holding the old slot token is cut off; the new one works.
    assert client.post(f"/api/slots/{slot_id}/start", headers={"X-Vaari-Slot-Token": old_slot_token}).status_code == 403
    assert client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": new_slot_token},
        files={"photo": ("s.jpg", TINY_JPEG, "image/jpeg")},
    ).status_code == 200


def test_link_routes_need_an_operator(client, auth_headers):
    setup_running_slot(client, auth_headers)
    m = _machine(client, auth_headers)
    assert client.post(f"/api/machines/{m['id']}/link/rotate").status_code == 401
    assert client.post(f"/api/machines/{m['id']}/link/revoke").status_code == 401
    assert client.post("/api/slots/1/record/revoke").status_code == 401
    assert client.post("/api/slots/1/record/reissue").status_code == 401


def test_record_link_expires_after_its_lifetime(client, auth_headers, monkeypatch):
    slot_id, slot_token, _ = setup_running_slot(client, auth_headers)
    rtoken = _finish(client, slot_id, slot_token)
    assert client.get(f"/api/records/{rtoken}").status_code == 200
    later(monkeypatch, 366)
    for url in (f"/api/records/{rtoken}", f"/api/records/{rtoken}/verify"):
        r = client.get(url)
        assert r.status_code == 410 and r.json()["error_code"] == "LINK_EXPIRED"


def test_revoke_and_reissue_record_link_keeps_the_hash(client, auth_headers):
    slot_id, slot_token, _ = setup_running_slot(client, auth_headers)
    rtoken = _finish(client, slot_id, slot_token)
    first = client.get(f"/api/records/{rtoken}").json()
    r = client.post(f"/api/slots/{slot_id}/record/revoke", headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    assert client.get(f"/api/records/{rtoken}").status_code == 410

    r = client.post(f"/api/slots/{slot_id}/record/reissue", headers=auth_headers)
    assert r.status_code == 200
    new_token = r.json()["record_token"]
    assert new_token != rtoken and r.json()["status"] == "active"
    assert client.get(f"/api/records/{rtoken}").status_code == 404
    second = client.get(f"/api/records/{new_token}").json()
    assert second["record_hash"] == first["record_hash"]
    assert client.get(f"/api/records/{new_token}/verify").json()["match"] is True


def test_record_routes_for_slot_without_record(client, auth_headers):
    slot_id, _, _ = setup_running_slot(client, auth_headers)
    r = client.post(f"/api/slots/{slot_id}/record/revoke", headers=auth_headers)
    assert r.status_code == 404


def test_older_rows_without_expiry_keep_working(client, auth_headers, temp_db):
    setup_running_slot(client, auth_headers)
    with temp_db() as s:
        m = s.query(Machine).first()
        m.link_expires_at = None
        s.commit()
        token = m.link_token
    assert client.get(f"/api/driver/{token}").status_code == 200
