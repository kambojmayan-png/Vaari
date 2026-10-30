"""Reader interface: mock, gemini_demo and the custom stub (pilot Part 5)."""

import json

import httpx
import pytest

from app.config import settings
from app.intake.custom import CustomModelReader
from app.intake.hosted import GeminiDemoReader, HostedVisionReader
from app.intake.reader import (
    MockRegisterReader,
    ReaderUnavailable,
    describe_reader,
    get_reader,
    reader_name,
)
from app.startup_checks import config_problems

GOOD = {
    "rows": [
        {
            "row": 1,
            "fields": {"phone": "9000000101", "name": "Synthetic A", "village": "Pind Kalan", "acres": 3.5,
                       "service_type": "super_seeder", "harvest_date": "2026-10-25", "note": None},
            "confidence": {"phone": 0.95, "name": 0.7, "village": 0.9, "acres": 0.9, "service_type": 0.9,
                           "harvest_date": 0.8},
        }
    ]
}


class S:
    reader = "mock"
    allow_hosted_reader = False
    vision_provider = "gemini"
    vision_model = ""
    custom_reader_url = ""
    custom_reader_token = ""
    reader_timeout_s = 5
    is_production = False


@pytest.mark.parametrize("raw,name", [("mock", "mock"), ("hosted", "gemini_demo"), ("gemini_demo", "gemini_demo"), ("custom", "custom"), (" MOCK ", "mock")])
def test_reader_names_and_aliases(raw, name):
    s = S()
    s.reader = raw
    assert reader_name(s) == name


def test_factory_returns_each_implementation():
    s = S()
    assert isinstance(get_reader(s), MockRegisterReader)
    s.reader = "gemini_demo"
    assert isinstance(get_reader(s), GeminiDemoReader)
    s.reader = "custom"
    assert isinstance(get_reader(s), CustomModelReader)
    s.reader = "tesseract"
    with pytest.raises(ReaderUnavailable):
        get_reader(s)


def test_describe_reader_says_who_gets_the_image():
    s = S()
    assert describe_reader(s).third_party is False and describe_reader(s).name == "mock"
    s.reader, s.vision_model = "gemini_demo", "model-x"
    d = describe_reader(s)
    assert (d.name, d.provider, d.model, d.third_party, d.demo_only) == ("gemini_demo", "Google Gemini", "model-x", True, True)
    s.reader, s.custom_reader_url = "custom", "http://10.0.0.5:9000/read"
    d = describe_reader(s)
    assert (d.name, d.provider, d.third_party) == ("custom", "10.0.0.5", False)


def test_no_hard_coded_model_names_in_the_code():
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[2] / "app"
    src = "".join(p.read_text(encoding="utf-8") for p in app_dir.rglob("*.py"))
    for name in ("gemini-2.5", "gemini-1.5", "gemini-2.0", "gemini-3", "flash-lite", "claude-3", "claude-3-5"):
        assert name not in src, name


def test_gemini_reader_without_model_refuses(monkeypatch):
    s = S()
    s.reader, s.allow_hosted_reader = "gemini_demo", True
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    with pytest.raises(ReaderUnavailable, match="VAARI_VISION_MODEL"):
        GeminiDemoReader(settings=s).read(b"\xff\xd8\xffimage")


def test_gemini_reader_sends_the_key_in_a_header_not_the_url(monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers, json):  # noqa: A002
            seen.update(url=url, headers=headers, body=json)
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": __import__("json").dumps(GOOD)}]}}]})

    monkeypatch.setattr("app.intake.hosted.httpx.Client", FakeClient)
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key-123")
    s = S()
    s.reader, s.allow_hosted_reader, s.vision_model = "gemini_demo", True, "gemini-model-x"
    draft = GeminiDemoReader(settings=s).read(b"\xff\xd8\xffimage")
    assert draft.rows[0].fields["phone"] == "9000000101"
    assert "synthetic-key-123" not in seen["url"] and "key=" not in seen["url"]
    assert seen["headers"]["x-goog-api-key"] == "synthetic-key-123"
    assert "/models/gemini-model-x:generateContent" in seen["url"]
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"


def test_unsupported_provider_is_refused(monkeypatch):
    s = S()
    s.reader, s.allow_hosted_reader, s.vision_model, s.vision_provider = "gemini_demo", True, "m", "anthropic"
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    with pytest.raises(ReaderUnavailable, match="not supported"):
        HostedVisionReader(settings=s).read(b"\xff\xd8\xffimage")


def _custom(handler, **kw):
    s = S()
    s.reader = "custom"
    s.custom_reader_url = kw.get("url", "http://127.0.0.1:9100/read")
    s.custom_reader_token = kw.get("token", "")
    return CustomModelReader(settings=s, transport=httpx.MockTransport(handler))


def test_custom_reader_posts_the_image_and_gets_the_same_draft_format():
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={**GOOD, "model": "vaari-reader-0"})

    draft = _custom(handler, token="private-token").read(b"\xff\xd8\xffimage", "image/jpeg")
    assert draft.reader == "custom"
    assert draft.rows[0].fields["acres"] == 3.5 and draft.rows[0].confidence["phone"] == 0.95
    assert seen["auth"] == "Bearer private-token"
    assert seen["body"]["media_type"] == "image/jpeg" and seen["body"]["image_base64"]
    assert "phone" in seen["body"]["fields"]


@pytest.mark.parametrize(
    "response, match",
    [(httpx.Response(500, text="boom"), "HTTP 500"), (httpx.Response(200, text="not json"), "invalid JSON")],
)
def test_custom_reader_failures_become_reader_unavailable(response, match):
    with pytest.raises(ReaderUnavailable, match=match):
        _custom(lambda r: response).read(b"\xff\xd8\xffimage")


def test_custom_reader_without_url_is_refused():
    s = S()
    s.reader = "custom"
    with pytest.raises(ReaderUnavailable, match="VAARI_CUSTOM_READER_URL"):
        CustomModelReader(settings=s).read(b"\xff\xd8\xffimage")


def test_startup_checks_for_reader_settings(monkeypatch):
    monkeypatch.setenv("VAARI_ENV", "development")
    monkeypatch.setenv("VAARI_READER", "gemini_demo")
    monkeypatch.setenv("VAARI_ALLOW_HOSTED_READER", "true")
    monkeypatch.delenv("VAARI_VISION_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    problems = config_problems(settings)
    assert any("VAARI_VISION_MODEL is required" in p for p in problems)
    assert any("GEMINI_API_KEY" in p for p in problems)
    monkeypatch.setenv("VAARI_READER", "nonsense")
    assert any("is not a reader" in p for p in config_problems(settings))
    monkeypatch.setenv("VAARI_READER", "custom")
    monkeypatch.setenv("VAARI_ALLOW_HOSTED_READER", "false")
    assert any("VAARI_CUSTOM_READER_URL" in p for p in config_problems(settings))


def test_custom_reader_is_not_a_third_party_in_production(monkeypatch):
    monkeypatch.setenv("VAARI_ENV", "production")
    monkeypatch.setenv("VAARI_SECRET_KEY", "s" * 40)
    monkeypatch.setenv("VAARI_READER", "custom")
    monkeypatch.setenv("VAARI_ALLOW_HOSTED_READER", "false")
    monkeypatch.setenv("VAARI_CUSTOM_READER_URL", "http://127.0.0.1:9100/read")
    assert config_problems(settings) == []
    monkeypatch.setenv("VAARI_CUSTOM_READER_URL", "http://reader.example.org/read")
    assert any("https://" in p for p in config_problems(settings))


def test_no_training_data_is_collected_or_stored():
    """Part 5: the custom-reader plan is documentation only; nothing collects training data yet."""
    import app.models  # noqa: F401
    from app.db import Base

    names = {t.name for t in Base.metadata.tables.values()}
    cols = {c.name for t in Base.metadata.tables.values() for c in t.columns}
    assert not any("train" in n for n in names | cols)


@pytest.mark.parametrize(
    "raw, expected",
    [("9.9-test", "gemini-9.9-test"), ("gemini-x", "gemini-x"), ("models/gemini-x", "gemini-x"), ("  ", "")],
)
def test_model_name_prefix_is_normalised_but_never_defaulted(raw, expected):
    """From main 23aac6a: a missing 'gemini-' prefix is added. Pilot rule: no default model."""
    from app.intake.hosted import normalize_model_name

    assert normalize_model_name(raw) == expected
