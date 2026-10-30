"""The mock reader never invents rows in production (pilot item C10, Docker deployment)."""

from tests.fixtures.synthetic_photos import TINY_JPEG


def test_mock_reader_refuses_in_production_and_keeps_the_photo(client, monkeypatch):
    from app.cli_users import create_user

    create_user("asha", "operator", "operator-password-123")
    monkeypatch.setenv("VAARI_ENV", "production")
    token = client.post("/api/auth/login", json={"username": "asha", "password": "operator-password-123"}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/intake/register-photo", headers=h, files={"photo": ("p.jpg", TINY_JPEG, "image/jpeg")})
    assert r.status_code == 503
    assert r.json()["error_code"] == "READER_UNAVAILABLE"
    intake_id = r.json()["details"]["intake_id"]
    # The photo is kept so staff can type the rows beside it.
    assert client.get(f"/api/intake/{intake_id}/image", headers=h).status_code == 200
    assert client.get("/api/health").json()["reader"] == "down"
