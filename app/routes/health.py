"""Health check route."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import clock
from app.config import settings
from app.db import get_db
from app.routes.intake import get_reader_status_for_health

router = APIRouter(tags=["health"])


def reader_detail() -> dict:
    """Which reader is in use, who receives the images, and the start-up probe's result."""
    from dataclasses import asdict

    from app.intake.probe import probe_state
    from app.intake.reader import describe_reader

    info = asdict(describe_reader(settings))
    info["probe"] = probe_state()
    return info


@router.get("/ready")
def get_ready(session: Session = Depends(get_db)):
    """Readiness for a load balancer or Docker: 200 when the server can do real work, else 503."""
    import secrets
    from pathlib import Path

    from app.errors import VaariError
    from app.migrate import current_revision, head_revision

    checks: dict[str, str] = {}
    try:
        session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
    try:
        checks["migrations"] = "ok" if current_revision() == head_revision() else "behind"
    except Exception:
        checks["migrations"] = "error"
    try:
        probe = Path(settings.data_dir) / f".ready-{secrets.token_hex(4)}"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"ok")
        probe.unlink()
        checks["storage"] = "ok"
    except Exception:
        checks["storage"] = "error"
    reader = get_reader_status_for_health()
    # A reader that is down is a visible fallback (people type rows), not a reason to stop serving.
    checks["reader"] = reader

    if all(checks[k] == "ok" for k in ("database", "migrations", "storage")):
        return {"status": "ready", "checks": checks}
    raise VaariError(
        error_code="NOT_READY",
        message="The server is not ready.",
        http_status=503,
        details={"checks": checks},
    )


@router.get("/health")
def get_health(session: Session = Depends(get_db)):
    db_status = "connected"
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    return {
        "status": "ok",
        "database": db_status,
        "reader": get_reader_status_for_health(),
        "satellite": "disabled",
        "messaging": "screen+wa_link",
        "today": clock.today().isoformat(),
        "demo_clock": bool(settings.today),
        "version": "0.1",
        "env": settings.env,
        "auth": settings.auth_mode,
        "reader_detail": reader_detail(),
    }
