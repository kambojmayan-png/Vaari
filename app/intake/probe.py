"""Start-up check of a remote register reader (pilot Part 5).

When the reader is ``gemini_demo`` (and switched on) or ``custom``, start-up
sends one tiny synthetic image ("VAARI PROBE", no real data) through the
normal reader path and records provider, model, latency and outcome.
``/api/health`` shows the result in ``reader_detail.probe``. It runs in a
background thread so a slow provider cannot hold up start-up. A failed probe
marks the reader ``down`` until a later call succeeds, so the intake screen
shows the type-the-rows fallback straight away.
"""

import io
import threading
from typing import Any

from app import clock

_lock = threading.Lock()
_state: dict[str, Any] = {"status": "not_run"}


def probe_image() -> bytes:
    """A small, plainly synthetic JPEG: white card, black text, no metadata."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 96), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([4, 4, 315, 91], outline="black", width=2)
    draw.text((16, 20), "VAARI PROBE", fill="black")
    draw.text((16, 52), "synthetic test image - no data", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def probe_state() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def _set(**values: Any) -> None:
    with _lock:
        _state.clear()
        _state.update(values)


def reset() -> None:
    _set(status="not_run")


def should_probe(settings: Any) -> bool:
    from app.intake.reader import reader_name

    name = reader_name(settings)
    if name == "gemini_demo":
        return bool(getattr(settings, "allow_hosted_reader", False))
    return name == "custom"


def run_probe(settings: Any = None) -> dict[str, Any]:
    """Send the synthetic image through the configured reader once, and record the outcome."""
    from app.intake.reader import describe_reader, get_reader

    if settings is None:
        from app.config import settings as app_settings
        settings = app_settings
    info = describe_reader(settings)
    base = {"provider": info.provider, "model": info.model, "reader": info.name}
    if not should_probe(settings):
        _set(status="not_run", **base)
        return probe_state()

    _set(status="pending", **base)
    started = clock.monotonic()
    try:
        draft = get_reader(settings).read(probe_image(), media_type="image/jpeg")
    except Exception as exc:
        from app.routes.intake import record_reader_failure

        record_reader_failure()
        _set(
            status="failed",
            latency_ms=round((clock.monotonic() - started) * 1000),
            checked_at=clock.iso_z(clock.now_utc()),
            error=f"{type(exc).__name__}: {str(exc)[:160]}",
            **base,
        )
    else:
        _set(
            status="ok",
            latency_ms=round((clock.monotonic() - started) * 1000),
            checked_at=clock.iso_z(clock.now_utc()),
            rows=len(draft.rows),
            **base,
        )
    from app.logging_setup import log_event

    st = probe_state()
    log_event(
        "reader probe", event="reader_probe", reader=info.name, provider=info.provider, model=info.model,
        ok=st["status"] == "ok", latency_ms=st.get("latency_ms"),
    )
    return st


def start_probe_in_background(settings: Any = None) -> threading.Thread | None:
    if settings is None:
        from app.config import settings as app_settings
        settings = app_settings
    if not should_probe(settings):
        reset()
        return None
    _set(status="pending")
    t = threading.Thread(target=run_probe, args=(settings,), name="vaari-reader-probe", daemon=True)
    t.start()
    return t
