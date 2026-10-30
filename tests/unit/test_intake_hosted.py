"""Unit tests for Step 03: HostedVisionReader (no network in tests)."""

import json
from datetime import date

import pytest

from app.intake.hosted import HostedVisionReader
from app.intake.prompt import PROMPT_VERSION
from app.intake.reader import ReaderUnavailable

TODAY = date(2026, 10, 25)
SAMPLE_IMAGE = b"\xff\xd8\xff\xe0dummy-jpeg"


class DummySettings:
    allow_hosted_reader = True
    vision_provider = "gemini"
    vision_model = "gemini-2.5-flash"
    reader_timeout_s = 20


def test_hosted_reader_refuses_when_allow_hosted_reader_is_false(monkeypatch):
    monkeypatch.setenv("VAARI_ALLOW_HOSTED_READER", "false")

    class LockedSettings(DummySettings):
        allow_hosted_reader = False

    reader = HostedVisionReader(settings=LockedSettings(), today_override=TODAY)
    with pytest.raises(ReaderUnavailable) as exc_info:
        reader.read(SAMPLE_IMAGE)
    assert "VAARI_ALLOW_HOSTED_READER" in str(exc_info.value)


def test_hosted_reader_retries_once_on_bad_json_and_succeeds():
    calls = []

    valid_payload = json.dumps(
        {
            "rows": [
                {
                    "row": 1,
                    "fields": {
                        "phone": "9000000101",
                        "name": "Gurpreet Singh",
                        "village": "Pind Kalan",
                        "acres": 3.5,
                        "service_type": "ਸੁਪਰ ਸੀਡਰ",
                        "harvest_date": "25/10",
                        "note": None,
                    },
                    "confidence": {
                        "phone": 0.95,
                        "name": 0.70,
                        "village": 0.90,
                        "acres": 0.90,
                        "service_type": 0.85,
                        "harvest_date": 0.80,
                    },
                }
            ]
        }
    )

    def fake_client(image: bytes, media_type: str, prompt: str, timeout_s: float) -> str:
        calls.append(prompt)
        if len(calls) == 1:
            return "NOT VALID JSON AT ALL {{{{"
        return valid_payload

    reader = HostedVisionReader(
        settings=DummySettings(),
        client_callable=fake_client,
        today_override=TODAY,
    )
    draft = reader.read(SAMPLE_IMAGE)

    assert len(calls) == 2
    assert "Return ONLY valid JSON" in calls[1]
    assert draft.reader == "hosted"
    assert draft.prompt_version == PROMPT_VERSION == "v2"  # v2: strict schema with confidence per field
    assert len(draft.rows) == 1
    assert draft.rows[0].fields["service_type"] == "super_seeder"
    assert draft.rows[0].fields["harvest_date"] == "2026-10-25"


def test_hosted_reader_raises_after_two_bad_json_responses():
    calls = []

    def always_bad_client(image: bytes, media_type: str, prompt: str, timeout_s: float) -> str:
        calls.append(prompt)
        return "Still broken JSON"

    reader = HostedVisionReader(
        settings=DummySettings(),
        client_callable=always_bad_client,
        today_override=TODAY,
    )
    with pytest.raises(ReaderUnavailable):
        reader.read(SAMPLE_IMAGE)
    assert len(calls) == 2


def test_hosted_reader_timeout_raises_reader_unavailable():
    def timeout_client(image: bytes, media_type: str, prompt: str, timeout_s: float) -> str:
        raise TimeoutError("Request timed out after 20s")

    reader = HostedVisionReader(
        settings=DummySettings(),
        client_callable=timeout_client,
        today_override=TODAY,
    )
    with pytest.raises(ReaderUnavailable) as exc_info:
        reader.read(SAMPLE_IMAGE)
    assert "timed out" in str(exc_info.value).lower()
