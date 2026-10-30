"""Photo storage interface, EXIF stripping and re-encoding (pilot item B7)."""

import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from app.config import settings
from app.errors import VaariError
from app.startup_checks import config_problems
from app.storage import LocalDiskStore, S3CompatibleStore, get_photo_store
from app.storage.sanitize import sanitize_image

GPS_IFD = 0x8825
ORIENTATION = 0x0112


def jpeg_with_gps(size=(40, 20), orientation=None) -> bytes:
    img = Image.new("RGB", size, (200, 120, 40))
    exif = Image.Exif()
    exif[0x010F] = "SyntheticPhoneMaker"  # Make
    exif[0x0110] = "SyntheticPhone 1"  # Model
    gps = exif.get_ifd(GPS_IFD)
    gps[1] = "N"
    gps[2] = (30.0, 44.0, 1.0)
    gps[3] = "E"
    gps[4] = (76.0, 46.0, 2.0)
    if orientation:
        exif[ORIENTATION] = orientation
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def test_fixture_really_has_gps():
    raw = jpeg_with_gps()
    assert Image.open(io.BytesIO(raw)).getexif().get_ifd(GPS_IFD)
    assert b"SyntheticPhoneMaker" in raw


def test_exif_and_gps_are_removed():
    clean = sanitize_image(jpeg_with_gps())
    img = Image.open(io.BytesIO(clean))
    assert img.format == "JPEG"
    assert len(img.getexif()) == 0
    assert b"Exif" not in clean
    assert b"SyntheticPhoneMaker" not in clean
    assert "icc_profile" not in img.info


def test_orientation_is_applied_before_stripping():
    # Orientation 6 = rotate 90 degrees clockwise to display.
    clean = sanitize_image(jpeg_with_gps(size=(40, 20), orientation=6))
    assert Image.open(io.BytesIO(clean)).size == (20, 40)


def test_png_with_transparency_becomes_rgb_jpeg():
    img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out = Image.open(io.BytesIO(sanitize_image(buf.getvalue())))
    assert out.format == "JPEG" and out.mode == "RGB"
    assert out.getpixel((4, 4))[0] > 240  # transparent -> white background


def test_same_input_gives_same_bytes():
    raw = jpeg_with_gps()
    assert sanitize_image(raw) == sanitize_image(raw)


def test_garbage_with_jpeg_magic_is_refused():
    with pytest.raises(VaariError) as exc:
        sanitize_image(b"\xff\xd8\xff" + b"not really a jpeg" * 10)
    assert exc.value.http_status == 422


def test_decompression_bomb_is_refused():
    img = Image.new("1", (9000, 9000))  # 81 million pixels, tiny file
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert len(buf.getvalue()) < 2_000_000
    with pytest.raises(VaariError):
        sanitize_image(buf.getvalue())


def test_local_store_round_trip(tmp_path):
    store = LocalDiskStore(root=tmp_path)
    ref = store.put("photos", "1_start_abc.jpg", b"data")
    assert ref.endswith("photos/1_start_abc.jpg")
    assert store.exists(ref) and store.get(ref) == b"data"
    assert not list(tmp_path.rglob("*.part"))
    # Older refs ("data/photos/...") resolve by their last two parts.
    assert store.get("data/photos/1_start_abc.jpg") == b"data"
    assert store.delete(ref) and not store.exists(ref)


@pytest.mark.parametrize("bad", ["../../etc/passwd", "photos/..", "secrets/x.jpg", "x.jpg"])
def test_local_store_rejects_bad_refs(tmp_path, bad):
    store = LocalDiskStore(root=tmp_path)
    assert store.exists(bad) is False
    with pytest.raises(ValueError):
        store.get(bad)


def test_unknown_area_refused(tmp_path):
    with pytest.raises(ValueError):
        LocalDiskStore(root=tmp_path).put("../outside", "x.jpg", b"x")


def test_s3_store_is_not_built_and_refused_at_startup(monkeypatch):
    with pytest.raises(NotImplementedError):
        S3CompatibleStore()
    monkeypatch.setenv("VAARI_PHOTO_STORE", "s3")
    with pytest.raises(NotImplementedError):
        get_photo_store()
    assert any("VAARI_PHOTO_STORE" in p for p in config_problems(settings))


def test_evidence_photo_is_stored_clean_and_hash_matches_file(client, auth_headers, temp_db):
    from app.models import Evidence
    from tests.api.test_step07_records_messages import setup_running_slot

    slot_id, token, _ = setup_running_slot(client, auth_headers)
    raw = jpeg_with_gps()
    r = client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": token},
        files={"photo": ("p.jpg", raw, "image/jpeg")},
    )
    assert r.status_code == 200
    with temp_db() as s:
        ev = s.query(Evidence).filter_by(slot_id=slot_id, kind="start").one()
        stored = Path(ev.photo_path).read_bytes()
        assert hashlib.sha256(stored).hexdigest() == ev.photo_sha256
        assert ev.photo_bytes == len(stored)
        assert b"SyntheticPhoneMaker" not in stored and b"Exif" not in stored
        assert ev.photo_path.endswith(".jpg")


def test_register_page_is_stored_and_served_clean(client, auth_headers):
    raw = jpeg_with_gps(size=(64, 48))
    r = client.post("/api/intake/register-photo", headers=auth_headers, files={"photo": ("r.jpg", raw, "image/jpeg")})
    assert r.status_code == 200
    img = client.get(f"/api/intake/{r.json()['intake_id']}/image", headers=auth_headers)
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/jpeg"
    assert b"SyntheticPhoneMaker" not in img.content and b"Exif" not in img.content


def test_unreadable_image_upload_gives_422(client, auth_headers):
    r = client.post(
        "/api/intake/register-photo",
        headers=auth_headers,
        files={"photo": ("r.jpg", b"\xff\xd8\xff" + b"junk" * 50, "image/jpeg")},
    )
    assert r.status_code == 422
    assert r.json()["error_code"] == "VALIDATION_ERROR"
