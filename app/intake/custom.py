"""Stub for a future custom register reader (pilot v0.2). See docs/FUTURE_CUSTOM_READER.md.

No custom model exists yet. This class is the client side of the contract a
future model must meet, so swapping it in needs only configuration:

- ``VAARI_READER=custom``
- ``VAARI_CUSTOM_READER_URL``: an endpoint on infrastructure the centre
  controls (localhost, a private address, or its own HTTPS server).
- ``VAARI_CUSTOM_READER_TOKEN`` (optional): sent as ``Authorization: Bearer``.

Request: ``POST`` JSON ``{"image_base64": "...", "media_type": "image/jpeg",
"prompt_version": "v2", "fields": [...]}``. Response: the same strict JSON as
the hosted reader, ``{"rows": [{"row", "fields", "confidence"}]}``, plus an
optional ``"model"`` string. The answer goes through the same validation, and
nothing skips the human confirmation screen.
"""

import base64
import time
from datetime import date
from typing import Any
from urllib.parse import urlparse

import httpx

from app.intake.draft_json import build_draft, parse_rows
from app.intake.prompt import PROMPT_VERSION
from app.intake.reader import CORE_FIELDS, ReaderInfo, ReaderUnavailable, RegisterDraft


class CustomModelReader:
    def __init__(self, settings: Any = None, transport: httpx.BaseTransport | None = None, today_override: date | None = None):
        if settings is None:
            from app.config import settings as app_settings
            settings = app_settings
        self.settings = settings
        self.transport = transport  # tests pass httpx.MockTransport
        self.today_override = today_override
        url = str(getattr(settings, "custom_reader_url", "") or "")
        self.info = ReaderInfo(
            name="custom",
            kind="custom",
            provider=urlparse(url).hostname or None,
            model=str(getattr(settings, "vision_model", "") or "").strip() or None,
            third_party=False,
        )

    def read(self, image: bytes, media_type: str = "image/jpeg") -> RegisterDraft:
        url = str(getattr(self.settings, "custom_reader_url", "") or "").strip()
        if not url:
            raise ReaderUnavailable("VAARI_CUSTOM_READER_URL is not set; there is no custom reader to call.")
        if not image:
            raise ReaderUnavailable("Uploaded register image is empty.")
        token = str(getattr(self.settings, "custom_reader_token", "") or "").strip()
        headers = {"content-type": "application/json"}
        if token:
            headers["authorization"] = f"Bearer {token}"
        body = {
            "image_base64": base64.b64encode(image).decode("ascii"),
            "media_type": media_type,
            "prompt_version": PROMPT_VERSION,
            "fields": list(CORE_FIELDS),
        }
        timeout_s = float(getattr(self.settings, "reader_timeout_s", 20))
        t0 = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout_s, transport=self.transport) as client:
                resp = client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise ReaderUnavailable(f"Custom reader timed out after {timeout_s}s") from exc
        except httpx.HTTPError as exc:
            raise ReaderUnavailable(f"Custom reader could not be reached ({type(exc).__name__})") from exc
        if resp.status_code != 200:
            raise ReaderUnavailable(f"Custom reader answered HTTP {resp.status_code}.")
        try:
            raw_rows = parse_rows(resp.text)
        except Exception as exc:
            raise ReaderUnavailable(f"Custom reader returned invalid JSON: {exc}") from exc
        latency_ms = max(1, int((time.perf_counter() - t0) * 1000))
        from app import clock

        return build_draft(
            raw_rows, self.today_override or clock.today(), reader="custom",
            prompt_version=PROMPT_VERSION, latency_ms=latency_ms,
        )
