"""The RegisterReader interface and the reader factory.

The rest of the app knows only ``RegisterReader.read(image, media_type) ->
RegisterDraft`` and ``get_reader()``. Three implementations exist:

- ``mock`` (default): returns the fixed synthetic draft in
  ``tests/fixtures/mock_register_draft.json``. Development and demos only;
  it refuses in production because it would invent rows.
- ``gemini_demo``: Google Gemini. DEMONSTRATION ONLY, synthetic pages only,
  off unless ``VAARI_ALLOW_HOSTED_READER=true``. Images go to a third party.
- ``custom``: a stub for a future model of Vaari's own, reached at
  ``VAARI_CUSTOM_READER_URL`` on infrastructure the centre controls. It sends
  the image and expects the same strict JSON as the hosted reader.

``VAARI_READER=hosted`` (the v0.1 name) still means ``gemini_demo``.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from app.intake.validate import FAILING_CONFIDENCE_CAP, validate_row


class ReaderUnavailable(Exception):
    """Raised when the register reader fails, times out, is disabled, or receives empty input."""


@dataclass
class RowDraft:
    row: int
    fields: dict[str, Any]
    confidence: dict[str, float] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


@dataclass
class RegisterDraft:
    rows: list[RowDraft]
    reader: str  # "mock" | "hosted" | "custom" (the v0.1 IntakeOut.reader values, plus custom)
    prompt_version: str
    latency_ms: int


@dataclass(frozen=True)
class ReaderInfo:
    """What the intake screen banner and /api/health say about the reader in use."""

    name: str  # mock | gemini_demo | custom | unknown
    kind: str  # mock | hosted | custom
    provider: str | None = None  # "Google Gemini", or the custom endpoint's host
    model: str | None = None
    third_party: bool = False  # True when images leave infrastructure the centre controls
    demo_only: bool = False


class RegisterReader(Protocol):
    info: ReaderInfo

    def read(self, image: bytes, media_type: str = "image/jpeg") -> RegisterDraft: ...


FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "fixtures"
    / "mock_register_draft.json"
)

CORE_FIELDS = ("phone", "name", "village", "acres", "service_type", "harvest_date")


def _current_today() -> date:
    """Read today via app.clock.today() if available, else fallback for standalone mode."""
    try:
        from app import clock
        return clock.today()
    except Exception:
        return date(2026, 10, 25)


class MockRegisterReader:
    """Deterministic mock reader returning the 6-row fixture from tests/fixtures/mock_register_draft.json."""

    info = ReaderInfo(name="mock", kind="mock", demo_only=True)

    def __init__(self, fixture_path: Path | None = None, today_override: date | None = None):
        self.fixture_path = fixture_path or FIXTURE_PATH
        self.today_override = today_override

    def read(self, image: bytes, media_type: str = "image/jpeg") -> RegisterDraft:
        from app.config import settings as app_settings

        if app_settings.is_production:
            # The mock returns the same invented rows for any photo. In production that would
            # put fictional farmers on the confirmation screen, so it refuses and staff type the rows.
            raise ReaderUnavailable("The mock reader is switched off in production. Type the rows from the photo.")

        if not image or len(image) == 0:
            raise ReaderUnavailable("Uploaded register image is empty.")

        if not self.fixture_path.exists():
            raise ReaderUnavailable(f"Mock fixture not found at {self.fixture_path}")

        raw_data = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        ref_today = self.today_override or _current_today()

        # If clock.today() in a test is more than 25 days away from the fixture's Oct 2026 dates,
        # anchor fixture validation to 2026-10-25 unless explicitly validating against ref_today.
        fixture_anchor = date(2026, 10, 25)
        val_today = ref_today if abs((ref_today - fixture_anchor).days) <= 25 else fixture_anchor

        rows: list[RowDraft] = []
        for item in raw_data.get("rows", []):
            row_no = int(item["row"])
            raw_fields = dict(item.get("fields") or {})
            conf: dict[str, float] = {
                k: float(v) for k, v in (item.get("confidence") or {}).items()
            }
            clean_fields, issues = validate_row(raw_fields, val_today, confidence=conf)

            # Ensure all core fields have a confidence entry
            for k in CORE_FIELDS:
                conf.setdefault(k, 0.9 if clean_fields.get(k) is not None else FAILING_CONFIDENCE_CAP)

            rows.append(
                RowDraft(
                    row=row_no,
                    fields=clean_fields,
                    confidence=conf,
                    issues=issues,
                )
            )

        return RegisterDraft(
            rows=rows,
            reader=raw_data.get("reader", "mock"),
            prompt_version=raw_data.get("prompt_version", "v1"),
            latency_ms=int(raw_data.get("latency_ms", 40)),
        )


READER_ALIASES = {"hosted": "gemini_demo", "gemini": "gemini_demo"}
READER_NAMES = ("mock", "gemini_demo", "custom")


def reader_name(settings: Any = None) -> str:
    """The configured reader's name after aliases: mock, gemini_demo, custom, or the raw unknown value."""
    if settings is None:
        from app.config import settings as app_settings
        settings = app_settings
    raw = str(getattr(settings, "reader", "mock")).strip().lower() or "mock"
    return READER_ALIASES.get(raw, raw)


def get_reader(settings: Any = None) -> RegisterReader:
    """Return the reader chosen by VAARI_READER (mock, gemini_demo or custom)."""
    if settings is None:
        from app.config import settings as app_settings
        settings = app_settings

    name = reader_name(settings)
    if name == "mock":
        return MockRegisterReader()
    if name == "gemini_demo":
        from app.intake.hosted import GeminiDemoReader
        return GeminiDemoReader(settings=settings)
    if name == "custom":
        from app.intake.custom import CustomModelReader
        return CustomModelReader(settings=settings)
    raise ReaderUnavailable(f"Unknown reader configured: '{name}'")


def describe_reader(settings: Any = None) -> ReaderInfo:
    """Describe the configured reader without calling it (for the banner and health)."""
    if settings is None:
        from app.config import settings as app_settings
        settings = app_settings
    name = reader_name(settings)
    if name == "mock":
        return MockRegisterReader.info
    if name == "gemini_demo":
        model = str(getattr(settings, "vision_model", "") or "").strip() or None
        return ReaderInfo(
            name="gemini_demo", kind="hosted", provider="Google Gemini", model=model, third_party=True, demo_only=True
        )
    if name == "custom":
        from urllib.parse import urlparse

        url = str(getattr(settings, "custom_reader_url", "") or "")
        host = urlparse(url).hostname or None
        model = str(getattr(settings, "vision_model", "") or "").strip() or None
        return ReaderInfo(name="custom", kind="custom", provider=host, model=model, third_party=False)
    return ReaderInfo(name="unknown", kind="mock")
