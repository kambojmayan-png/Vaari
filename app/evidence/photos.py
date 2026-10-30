"""Photo upload processing: size limit, magic bytes, metadata stripping, SHA-256 and storage."""

import hashlib

from fastapi import UploadFile

from app.config import settings
from app.errors import VaariError
from app.storage import get_photo_store
from app.storage.sanitize import sanitize_image


def detect_image_type(raw: bytes) -> str | None:
    """Return 'jpg', 'png' or 'webp' from the magic bytes, else None."""
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"RIFF") and len(raw) >= 12 and raw[8:12] == b"WEBP":
        return "webp"
    return None


async def read_image_upload(file: UploadFile) -> bytes:
    """Read an upload with the size limit and check it is a JPEG, PNG or WebP by its bytes."""
    max_bytes = int(settings.max_photo_mb * 1024 * 1024)
    # Read max_bytes + 1 to detect oversize without loading unbounded file
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise VaariError(
            error_code="PAYLOAD_TOO_LARGE",
            message=f"Photo exceeds {settings.max_photo_mb} MB limit.",
            http_status=413,
            details={"max_mb": settings.max_photo_mb},
        )
    if len(raw) == 0:
        raise VaariError(
            error_code="VALIDATION_ERROR",
            message="Uploaded file is empty.",
            http_status=422,
            details={"field": "photo"},
        )
    if detect_image_type(raw) is None:
        raise VaariError(
            error_code="VALIDATION_ERROR",
            message="Uploaded file is not a valid JPEG, PNG or WebP image.",
            http_status=422,
            details={"field": "photo"},
        )
    return raw


async def process_photo(
    slot_id: int,
    kind: str,
    file: UploadFile | None,
) -> tuple[str | None, str | None, int | None]:
    """Validate, strip metadata, re-encode, hash and store an evidence photo.

    Returns (photo_ref, photo_sha256, photo_bytes). Since pilot v0.2 the hash and
    size are of the stored, cleaned JPEG, so the file on disk can always be
    checked against the record.
    """
    if file is None:
        return None, None, None

    raw = await read_image_upload(file)
    clean = sanitize_image(raw)
    sha = hashlib.sha256(clean).hexdigest()
    filename = f"{slot_id}_{kind}_{sha[:12]}.jpg"
    ref = get_photo_store().put("photos", filename, clean)
    return ref, sha, len(clean)
