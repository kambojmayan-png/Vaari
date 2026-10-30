"""API routes for register photo intake, stored drafts, and human confirmation (Step 05)."""

import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import clock
from app.auth import Principal, require_operator
from app.config import settings
from app.db import get_db
from app.enums import ServiceType
from app.errors import VaariError
from app.event_log import log_event
from app.evidence.photos import read_image_upload
from app.intake.preprocess import VALID_TURNS, preprocess_for_reader, rotate_clockwise
from app.intake.prompt import PROMPT_VERSION
from app.intake.reader import ReaderUnavailable, get_reader, reader_name
from app.intake.validate import has_blocking_issues, is_warning, validate_row
from app.logging_setup import log_event as app_log_event
from app.models import IntakePage, RegisterDraft
from app.routes.common import get_or_create_home_centre
from app.routes.requests import create_request_record
from app.scheduler.service import run_for_centre
from app.schemas import RequestIn
from app.storage import get_photo_store
from app.storage.sanitize import sanitize_image

router = APIRouter(prefix="/intake", tags=["intake"])

# Track the timestamp of the most recent reader failure for GET /api/health
_last_reader_failure_at: datetime | None = None


def record_reader_failure() -> None:
    global _last_reader_failure_at
    _last_reader_failure_at = clock.now_utc()


def clear_reader_failure() -> None:
    global _last_reader_failure_at
    _last_reader_failure_at = None
    from app.intake.probe import probe_state, reset

    if probe_state().get("status") == "failed":
        reset()


def get_reader_status_for_health() -> str:
    """Return 'mock', 'hosted', 'custom' or 'down' (down if the last call failed within 5 minutes or it is off)."""
    global _last_reader_failure_at
    now = clock.now_utc()
    from app.intake.probe import probe_state

    if probe_state().get("status") == "failed" and _last_reader_failure_at is not None:
        return "down"  # a failed start-up probe stays visible until a real call succeeds
    if _last_reader_failure_at is not None:
        if (now - _last_reader_failure_at) <= timedelta(minutes=5):
            return "down"

    mode = reader_name(settings)
    if mode == "mock":
        # The mock refuses in production (it would invent rows), so show the fallback.
        return "down" if settings.is_production else "mock"
    if mode == "gemini_demo":
        if not settings.allow_hosted_reader:
            return "down"
        return "hosted"
    if mode == "custom":
        return "custom" if settings.custom_reader_url else "down"
    return "down"


async def _validate_and_save_register_photo(
    file: UploadFile | None,
    rotate: int = 0,
) -> tuple[str, str, bytes]:
    """Validate, strip metadata and re-encode a register photo, store it.

    Returns (stored ref, sha256 of the stored JPEG, the stored JPEG bytes).
    """
    if file is None:
        raise VaariError(
            error_code="VALIDATION_ERROR",
            message="Register photo is required.",
            http_status=422,
            details={"field": "photo"},
        )

    raw = await read_image_upload(file)
    clean = rotate_clockwise(sanitize_image(raw), rotate)
    sha = hashlib.sha256(clean).hexdigest()
    ref = get_photo_store().put("register_pages", f"register_{sha[:12]}.jpg", clean)
    return ref, sha, clean


def _serialize_intake_page(session: Session, page: IntakePage) -> dict[str, Any]:
    drafts = (
        session.query(RegisterDraft)
        .filter_by(intake_page_id=page.id)
        .order_by(RegisterDraft.row_no.asc())
        .all()
    )
    reader_name_for_page, third_party = {
        "hosted": ("gemini_demo", True),
        "custom": ("custom", False),
    }.get(page.reader, (page.reader, False))
    return {
        "intake_id": page.id,
        "reader": page.reader,
        "reader_name": reader_name_for_page,
        "third_party": third_party,
        "latency_ms": page.latency_ms,
        "status": page.status,
        "rows": [
            {
                "row": d.row_no,
                "fields": d.row_json or {},
                "confidence": d.confidence_json or {},
                "issues": d.issues_json or [],
            }
            for d in drafts
        ],
    }


@router.post("/register-photo")
async def upload_register_photo(
    photo: UploadFile | None = File(None),
    rotate: int = Form(0),
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
) -> dict[str, Any]:
    if rotate not in VALID_TURNS:
        raise VaariError(
            error_code="VALIDATION_ERROR",
            message="rotate must be 0, 90, 180 or 270.",
            http_status=422,
            details={"field": "rotate"},
        )
    image_path, image_sha256, stored_bytes = await _validate_and_save_register_photo(photo, rotate)
    # Every reader gets the preprocessed copy: upright, 1000-2000 px, greyscale, contrast stretched.
    reader_bytes, _prep = preprocess_for_reader(stored_bytes)
    media_type = "image/jpeg"

    home_centre = get_or_create_home_centre(session)
    now = clock.now_utc()

    page = IntakePage(
        centre_id=home_centre.id,
        image_path=image_path,
        image_sha256=image_sha256,
        image_delete_after=now + timedelta(days=7),
        reader={"gemini_demo": "hosted"}.get(reader_name(settings), reader_name(settings)),
        prompt_version=PROMPT_VERSION,
        latency_ms=None,
        status="drafted",
        error=None,
        created_at=now,
    )
    session.add(page)
    session.flush()


    try:
        reader = get_reader(settings)
        draft_result = reader.read(reader_bytes, media_type=media_type)
        clear_reader_failure()
    except (ReaderUnavailable, Exception) as exc:
        record_reader_failure()
        app_log_event("reader call", event="reader_call", reader=settings.reader, ok=False, error_type=type(exc).__name__)
        page.status = "failed"
        page.error = str(exc)
        log_event(
            session=session,
            actor="operator",
            entity="intake_page",
            entity_id=page.id,
            event="failed",
            payload={"error": str(exc)},
        )
        session.commit()
        raise VaariError(
            error_code="READER_UNAVAILABLE",
            message="Reader unavailable: type the rows.",
            http_status=503,
            details={"intake_id": page.id},
        ) from exc

    app_log_event(
        "reader call", event="reader_call", reader=draft_result.reader, ok=True,
        latency_ms=draft_result.latency_ms, rows=len(draft_result.rows),
    )
    page.reader = draft_result.reader
    page.prompt_version = draft_result.prompt_version
    page.latency_ms = draft_result.latency_ms
    page.status = "drafted"

    for r in draft_result.rows:
        draft_row = RegisterDraft(
            intake_page_id=page.id,
            row_no=r.row,
            row_json=r.fields,
            confidence_json=r.confidence,
            issues_json=r.issues,
            edited=False,
            edited_fields_json={},
            skipped=False,
            confirmed_at=None,
            request_id=None,
        )
        session.add(draft_row)

    log_event(
        session=session,
        actor="operator",
        entity="intake_page",
        entity_id=page.id,
        event="drafted",
        payload={"reader": page.reader, "rows": len(draft_result.rows)},
    )
    session.commit()
    return _serialize_intake_page(session, page)


@router.get("/{id}")
def get_intake_draft(
    id: int,
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
) -> dict[str, Any]:
    page = session.query(IntakePage).filter_by(id=id).first()
    if page is None or page.status == "confirmed":
        raise VaariError(
            error_code="DRAFT_NOT_FOUND",
            message="The intake draft does not exist or was already confirmed.",
            http_status=404,
        )
    return _serialize_intake_page(session, page)


@router.get("/{id}/image")
def get_intake_image(
    id: int,
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
):
    page = session.query(IntakePage).filter_by(id=id).first()
    if page is None:
        raise VaariError(
            error_code="DRAFT_NOT_FOUND",
            message="The intake draft does not exist.",
            http_status=404,
        )

    store = get_photo_store()
    if not page.image_path or not store.exists(page.image_path):
        raise VaariError("NOT_FOUND", "Register page image file not found.", 404)

    return Response(content=store.get(page.image_path), media_type="image/jpeg")


@router.post("/{id}/confirm", status_code=status.HTTP_201_CREATED)
def confirm_intake(
    id: int,
    payload: dict[str, Any],
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_operator),
) -> dict[str, Any]:
    page = session.query(IntakePage).filter_by(id=id).first()
    if page is None or page.status == "confirmed":
        raise VaariError(
            error_code="DRAFT_NOT_FOUND",
            message="The intake draft does not exist or was already confirmed.",
            http_status=404,
        )

    rows_input = payload.get("rows")
    if not isinstance(rows_input, list):
        raise VaariError(
            error_code="VALIDATION_ERROR",
            message="rows list is required.",
            http_status=422,
            details={"field": "rows"},
        )

    drafts_by_row: dict[int, RegisterDraft] = {
        d.row_no: d
        for d in session.query(RegisterDraft).filter_by(intake_page_id=page.id).all()
    }

    today = clock.today()
    now = clock.now_utc()
    home_centre = get_or_create_home_centre(session)

    created_request_ids: list[int] = []
    skipped_rows: list[int] = []
    errors: list[dict[str, Any]] = []
    seen_row_nos: set[int] = set()

    for item in rows_input:
        if not isinstance(item, dict) or "row" not in item:
            continue
        row_no = int(item["row"])
        seen_row_nos.add(row_no)
        skip_flag = bool(item.get("skip", False))
        draft = drafts_by_row.get(row_no)

        if skip_flag:
            skipped_rows.append(row_no)
            if draft is not None:
                draft.skipped = True
                draft.confirmed_at = now
            continue

        # If this row was already confirmed in an earlier partial submission, include its request_id
        if draft is not None and draft.request_id is not None:
            created_request_ids.append(draft.request_id)
            continue

        raw_fields = dict(item.get("fields") or {})
        clean_fields, row_issues = validate_row(raw_fields, today)

        # Check consent_service (defaults to True if omitted by minimal API callers)
        consent_service = bool(item.get("consent_service", True))
        consent_evidence = bool(item.get("consent_evidence", True))
        consent_share = bool(item.get("consent_share", True))

        if not consent_service:
            row_issues.append("consent_service: farmer service consent is required")

        if has_blocking_issues(row_issues):
            blocking = [iss for iss in row_issues if not is_warning(iss)]
            first_issue = blocking[0] if blocking else row_issues[0]
            failing_field = first_issue.split(":")[0].strip() if ":" in first_issue else "row"
            errors.append(
                {
                    "row": row_no,
                    "field": failing_field,
                    "issues": blocking,
                    "message": first_issue,
                }
            )
            if draft is not None:
                draft.issues_json = row_issues
            continue

        # Track edits against stored draft
        if draft is not None:
            orig_fields = draft.row_json or {}
            edited_diff: dict[str, Any] = {}
            for k in ("phone", "name", "village", "acres", "service_type", "harvest_date", "note"):
                if k in raw_fields and orig_fields.get(k) != clean_fields.get(k):
                    edited_diff[k] = clean_fields.get(k)
            draft.edited = len(edited_diff) > 0
            draft.edited_fields_json = edited_diff
            draft.row_json = clean_fields
            draft.issues_json = row_issues

        hd_str = clean_fields.get("harvest_date")
        parsed_hd = date.fromisoformat(hd_str) if hd_str else None

        req_in = RequestIn(
            phone=str(clean_fields["phone"]),
            name=clean_fields.get("name"),
            village=str(clean_fields["village"]),
            acres=float(clean_fields["acres"]),
            service_type=ServiceType(str(clean_fields["service_type"])),
            harvest_date=parsed_hd,
            consent_service=consent_service,
            consent_evidence=consent_evidence,
            consent_share=consent_share,
        )

        req = create_request_record(
            session=session,
            payload=req_in,
            source="register",
            run_scheduler=False,
            extra_log_payload={"intake_id": page.id, "row": row_no},
        )
        created_request_ids.append(req.id)

        if draft is not None:
            draft.confirmed_at = now
            draft.request_id = req.id

    # Any draft rows omitted from payload are treated as skipped when no errors occurred
    for r_no, draft in drafts_by_row.items():
        if r_no not in seen_row_nos and not draft.skipped and draft.request_id is None:
            draft.skipped = True
            draft.confirmed_at = now
            skipped_rows.append(r_no)

    # Mark page confirmed when there are no blocking row errors left
    if len(errors) == 0:
        page.status = "confirmed"
        page.image_delete_after = now + timedelta(days=7)

    log_event(
        session=session,
        actor="operator",
        entity="intake_page",
        entity_id=page.id,
        event="confirmed",
        payload={
            "created_request_ids": created_request_ids,
            "skipped_rows": sorted(skipped_rows),
            "errors_count": len(errors),
        },
    )

    # Run the scheduler once at the end
    run_for_centre(session, home_centre.id)
    session.commit()

    return {
        "created_request_ids": created_request_ids,
        "skipped_rows": sorted(skipped_rows),
        "errors": errors,
    }


def purge_expired_register_images(session: Session, dry_run: bool = False) -> list[str]:
    """Delete register page images past image_delete_after and return deleted paths."""
    now = clock.now_utc()
    store = get_photo_store()
    pages = session.query(IntakePage).all()
    deleted: list[str] = []

    for p in pages:
        del_after = p.image_delete_after
        if del_after is None:
            continue
        if del_after.tzinfo is None:
            del_after = del_after.replace(tzinfo=timezone.utc)
        if del_after <= now and p.image_path:
            if store.exists(p.image_path):
                deleted.append(p.image_path)
                if not dry_run:
                    store.delete(p.image_path)
                    log_event(
                        session=session,
                        actor="system",
                        entity="intake_page",
                        entity_id=p.id,
                        event="image_purged",
                        payload={"image_path": p.image_path},
                    )

    if not dry_run and deleted:
        session.commit()
    return deleted
