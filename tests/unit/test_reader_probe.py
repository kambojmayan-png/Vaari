"""Start-up probe of a remote reader, reported in /api/health (pilot Part 5)."""

import io

import pytest
from PIL import Image

from app.intake import probe
from app.intake.reader import ReaderInfo, ReaderUnavailable, RegisterDraft


@pytest.fixture(autouse=True)
def clean_probe():
    import app.routes.intake as intake_route

    probe.reset()
    intake_route.clear_reader_failure()
    yield
    probe.reset()
    intake_route.clear_reader_failure()


class FakeReader:
    info = ReaderInfo(name="gemini_demo", kind="hosted", provider="Google Gemini", model="model-x", third_party=True)

    def __init__(self, fail=False):
        self.fail = fail
        self.images = []

    def read(self, image, media_type="image/jpeg"):
        self.images.append(image)
        if self.fail:
            raise ReaderUnavailable("Gemini answered HTTP 403.")
        return RegisterDraft(rows=[], reader="hosted", prompt_version="v2", latency_ms=5)


@pytest.fixture
def gemini_on(monkeypatch):
    monkeypatch.setenv("VAARI_READER", "gemini_demo")
    monkeypatch.setenv("VAARI_ALLOW_HOSTED_READER", "true")
    monkeypatch.setenv("VAARI_VISION_MODEL", "model-x")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")


def test_probe_image_is_small_synthetic_and_clean():
    raw = probe.probe_image()
    img = Image.open(io.BytesIO(raw))
    assert img.size == (320, 96) and len(raw) < 20_000
    assert len(img.getexif()) == 0


def test_probe_success_is_reported_in_health(client, gemini_on, monkeypatch):
    fake = FakeReader()
    monkeypatch.setattr("app.intake.reader.get_reader", lambda s=None: fake)
    st = probe.run_probe()
    assert st["status"] == "ok" and st["provider"] == "Google Gemini" and st["model"] == "model-x"
    assert isinstance(st["latency_ms"], int) and st["checked_at"].endswith("Z")
    assert fake.images == [probe.probe_image()]
    h = client.get("/api/health").json()
    assert h["reader"] == "hosted"
    d = h["reader_detail"]
    assert (d["name"], d["provider"], d["model"], d["third_party"]) == ("gemini_demo", "Google Gemini", "model-x", True)
    assert d["probe"]["status"] == "ok"


def test_probe_failure_shows_reader_down(client, gemini_on, monkeypatch):
    monkeypatch.setattr("app.intake.reader.get_reader", lambda s=None: FakeReader(fail=True))
    st = probe.run_probe()
    assert st["status"] == "failed" and "403" in st["error"]
    h = client.get("/api/health").json()
    assert h["reader"] == "down"
    assert h["reader_detail"]["probe"]["status"] == "failed"


def test_no_probe_for_mock_or_when_the_hosted_reader_is_off(client, monkeypatch):
    called = []
    monkeypatch.setattr("app.intake.reader.get_reader", lambda s=None: called.append(1))
    monkeypatch.setenv("VAARI_READER", "mock")
    assert probe.run_probe()["status"] == "not_run"
    monkeypatch.setenv("VAARI_READER", "gemini_demo")
    monkeypatch.setenv("VAARI_ALLOW_HOSTED_READER", "false")
    assert probe.run_probe()["status"] == "not_run"
    assert called == []  # nothing was sent
    assert client.get("/api/health").json()["reader_detail"]["name"] == "gemini_demo"


def test_background_probe_runs_at_startup(gemini_on, monkeypatch, temp_db):
    from fastapi.testclient import TestClient

    from app.main import app

    fake = FakeReader()
    monkeypatch.setattr("app.intake.reader.get_reader", lambda s=None: fake)
    monkeypatch.setenv("VAARI_READER_PROBE", "true")
    with TestClient(app) as c:
        for _ in range(50):
            if probe.probe_state()["status"] == "ok":
                break
            import time

            time.sleep(0.02)
        assert c.get("/api/health").json()["reader_detail"]["probe"]["status"] == "ok"
    assert len(fake.images) == 1
