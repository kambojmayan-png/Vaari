"""Hosted vision reader: Google Gemini, for DEMONSTRATION ONLY (pilot v0.2).

PRIVACY GATE: refuses to run unless VAARI_ALLOW_HOSTED_READER is "true".
Images go to Google, a third party. Use synthetic register pages only. No
real register page may ever be sent to a hosted model. Production refuses to
start with it on unless VAARI_ALLOW_HOSTED_READER_IN_PRODUCTION=true.

There is no default model name: VAARI_VISION_MODEL must name a current
Gemini model, so an outdated hard-coded name can never be used silently.
The key is read from GEMINI_API_KEY (keep it in .env) and sent in the
``x-goog-api-key`` header, never in the URL, so it cannot end up in a log.
"""

import base64
import os
import time
from datetime import date
from typing import Any, Callable

import httpx

from app.intake.draft_json import build_draft, parse_rows
from app.intake.prompt import (
    PROMPT_VERSION,
    REGISTER_EXTRACTION_PROMPT,
    RESPONSE_SCHEMA,
    RETRY_JSON_MESSAGE,
)
from app.intake.reader import ReaderInfo, ReaderUnavailable, RegisterDraft

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def normalize_model_name(raw: str) -> str:
    """'x-pro' -> 'gemini-x-pro'; 'models/gemini-x' -> 'gemini-x'; '' stays ''.

    Kept from main (23aac6a): people often type the model without its prefix. There is
    still no default model: an empty value means the reader is not configured.
    """
    name = raw.strip()
    if name.startswith("models/"):
        name = name[len("models/"):]
    if name and not name.startswith("gemini-"):
        name = f"gemini-{name}"
    return name


def _get_today() -> date:
    try:
        from app import clock
        return clock.today()
    except Exception:
        return date(2026, 10, 25)


class HostedVisionReader:
    """Calls a hosted vision model with one retry on invalid JSON, then validates every cell.

    ``client_callable(image, media_type, prompt, timeout_s) -> str`` replaces the
    network call in tests.
    """

    info = ReaderInfo(name="gemini_demo", kind="hosted", provider="Google Gemini", third_party=True, demo_only=True)

    def __init__(
        self,
        settings: Any = None,
        client_callable: Callable[[bytes, str, str, float], str] | None = None,
        today_override: date | None = None,
    ):
        if settings is None:
            from app.config import settings as app_settings
            settings = app_settings
        self.settings = settings
        self.client_callable = client_callable
        self.today_override = today_override
        model = str(getattr(settings, "vision_model", "") or "").strip() or None
        self.info = ReaderInfo(
            name="gemini_demo", kind="hosted", provider="Google Gemini", model=model, third_party=True, demo_only=True
        )

    def _check_privacy_gate(self) -> None:
        allow_attr = getattr(self.settings, "allow_hosted_reader", False)
        env_raw = os.environ.get("VAARI_ALLOW_HOSTED_READER", "").strip().lower()
        is_allowed = (allow_attr is True) or (env_raw == "true")
        if not is_allowed:
            raise ReaderUnavailable(
                "Hosted vision reader is disabled. Set VAARI_ALLOW_HOSTED_READER=true "
                "only when testing with synthetic register pages."
            )

    def read(self, image: bytes, media_type: str = "image/jpeg") -> RegisterDraft:
        self._check_privacy_gate()

        if not image or len(image) == 0:
            raise ReaderUnavailable("Uploaded register image is empty.")

        timeout_s = float(getattr(self.settings, "reader_timeout_s", 20))
        t0 = time.perf_counter()

        prompt = REGISTER_EXTRACTION_PROMPT
        raw_rows: list[dict[str, Any]] | None = None
        last_error: Exception | None = None

        # Try once, and if JSON fails to parse or breaks schema, retry ONCE with RETRY_JSON_MESSAGE
        for attempt in range(2):
            current_prompt = prompt if attempt == 0 else f"{prompt}\n\n{RETRY_JSON_MESSAGE}"
            try:
                if self.client_callable is not None:
                    raw_text = self.client_callable(image, media_type, current_prompt, timeout_s)
                else:
                    raw_text = self._invoke_provider(image, media_type, current_prompt, timeout_s)
            except ReaderUnavailable:
                raise
            except (TimeoutError, httpx.TimeoutException) as exc:
                raise ReaderUnavailable(f"Vision provider timed out after {timeout_s}s") from exc
            except Exception as exc:
                raise ReaderUnavailable(f"Vision provider call failed ({type(exc).__name__})") from exc

            try:
                raw_rows = parse_rows(raw_text)
                break
            except Exception as parse_exc:
                last_error = parse_exc

        if raw_rows is None:
            raise ReaderUnavailable(f"Vision model returned invalid JSON after retry: {last_error}")

        latency_ms = max(1, int((time.perf_counter() - t0) * 1000))
        return build_draft(
            raw_rows,
            self.today_override or _get_today(),
            reader="hosted",
            prompt_version=PROMPT_VERSION,
            latency_ms=latency_ms,
        )

    def _invoke_provider(self, image: bytes, media_type: str, prompt: str, timeout_s: float) -> str:
        provider = str(getattr(self.settings, "vision_provider", "gemini")).strip().lower()
        if provider != "gemini":
            raise ReaderUnavailable(
                f"VAARI_VISION_PROVIDER='{provider}' is not supported. The demo reader uses Gemini only."
            )
        model = normalize_model_name(str(getattr(self.settings, "vision_model", "") or ""))
        if not model:
            raise ReaderUnavailable("VAARI_VISION_MODEL is not set. Name a current Gemini vision model.")
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ReaderUnavailable("GEMINI_API_KEY is not set (keep it in .env).")

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": media_type, "data": base64.b64encode(image).decode("ascii")}},
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
            },
        }
        with httpx.Client(timeout=timeout_s) as http_client:
            resp = http_client.post(
                GEMINI_ENDPOINT.format(model=model),
                headers={"x-goog-api-key": api_key, "content-type": "application/json"},
                json=payload,
            )
        if resp.status_code != 200:
            # Status only: the body can echo the request.
            raise ReaderUnavailable(f"Gemini answered HTTP {resp.status_code}.")
        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ReaderUnavailable("Gemini answered without any text.") from exc


class GeminiDemoReader(HostedVisionReader):
    """The ``gemini_demo`` reader. Same behaviour as HostedVisionReader; the name says what it is."""
