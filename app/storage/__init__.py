"""Photo storage behind one interface (pilot item B7).

Everything that saves or reads an uploaded image goes through
``get_photo_store()``. Only ``LocalDiskStore`` is built. An S3-compatible
store can be added later by implementing ``PhotoStore``; until then
``VAARI_PHOTO_STORE=s3`` is refused at start-up so nobody believes photos are
going somewhere they are not.

A stored reference ("ref") ends in ``<area>/<filename>``. For the local store
it is the file's path under VAARI_DATA_DIR, as in v0.1.0, for example
``data/photos/12_start_ab12cd34ef56.jpg``. Only the last two parts are used to
find the file, so a ref still resolves if VAARI_DATA_DIR moves.
"""

from pathlib import Path
from typing import Protocol

from app.config import settings

AREAS = ("photos", "register_pages")


class PhotoStore(Protocol):
    name: str

    def put(self, area: str, filename: str, data: bytes) -> str: ...

    def get(self, ref: str) -> bytes: ...

    def exists(self, ref: str) -> bool: ...

    def delete(self, ref: str) -> bool: ...


def _split(ref: str) -> tuple[str, str]:
    parts = Path(ref).parts
    if len(parts) < 2 or parts[-2] not in AREAS:
        raise ValueError(f"Not a photo reference: {ref!r}")
    name = parts[-1]
    if name in ("", ".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"Bad file name in reference: {ref!r}")
    return parts[-2], name


class LocalDiskStore:
    """Files under VAARI_DATA_DIR/<area>/. Written atomically (temp file, then rename)."""

    name = "local"

    def __init__(self, root: Path | None = None):
        self._root = root

    @property
    def root(self) -> Path:
        return self._root or Path(settings.data_dir)

    def path_for(self, ref: str) -> Path:
        area, name = _split(ref)
        return self.root / area / name

    def put(self, area: str, filename: str, data: bytes) -> str:
        if area not in AREAS:
            raise ValueError(f"Unknown area {area!r}")
        ref = (self.root / area / filename).as_posix()
        target = self.path_for(ref)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(target)
        return ref

    def get(self, ref: str) -> bytes:
        return self.path_for(ref).read_bytes()

    def exists(self, ref: str) -> bool:
        try:
            return self.path_for(ref).is_file()
        except ValueError:
            return False

    def delete(self, ref: str) -> bool:
        try:
            p = self.path_for(ref)
        except ValueError:
            return False
        if p.is_file():
            p.unlink()
            return True
        return False


class S3CompatibleStore:
    """Placeholder for an S3-compatible bucket (MinIO, AWS S3, GCS interop). Not built."""

    name = "s3"

    def __init__(self) -> None:
        raise NotImplementedError(
            "The S3-compatible photo store is not built yet. Use VAARI_PHOTO_STORE=local. "
            "See docs/DEPLOY.md for what implementing it involves."
        )


def get_photo_store() -> PhotoStore:
    kind = settings.photo_store
    if kind == "local":
        return LocalDiskStore()
    if kind == "s3":
        return S3CompatibleStore()
    raise ValueError(f"Unknown VAARI_PHOTO_STORE {kind!r} (use 'local').")
