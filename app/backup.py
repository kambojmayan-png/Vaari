"""Backup and restore (pilot item B8).

A backup is one folder::

    vaari-backup-20261030T101500Z/
        vaari.sqlite        made with SQLite's online backup API (safe while the server runs)
        photos/             evidence photos
        register_pages/     register page images not yet purged
        manifest.json       SHA-256 of every file, row counts, schema revision

``restore`` checks every hash and the database's integrity before touching
anything, keeps the current database and photos beside the originals as
``*.pre-restore-<time>``, copies the backup in, and upgrades the schema if
the backup is older. Stop the server before restoring.
"""

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from app import clock

MANIFEST = "manifest.json"
DB_NAME = "vaari.sqlite"
PHOTO_AREAS = ("photos", "register_pages")
BACKUP_PREFIX = "vaari-backup-"


class BackupError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _stamp() -> str:
    return clock.now_utc().strftime("%Y%m%dT%H%M%SZ")


def _integrity_ok(db_file: Path) -> bool:
    con = sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


def _row_counts(db_file: Path) -> dict[str, int]:
    con = sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True)
    try:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        con.close()


def _revision(db_file: Path) -> str | None:
    con = sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True)
    try:
        return con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        con.close()


def create_backup(db_path: Path, data_dir: Path, out_root: Path) -> Path:
    """Make a verified backup folder under out_root and return its path."""
    db_path, data_dir, out_root = Path(db_path), Path(data_dir), Path(out_root)
    if not db_path.exists():
        raise BackupError(f"No database at {db_path}.")
    target = out_root / f"{BACKUP_PREFIX}{_stamp()}"
    n = 1
    while target.exists():
        n += 1
        target = out_root / f"{BACKUP_PREFIX}{_stamp()}-{n}"
    work = target.with_name(target.name + ".part")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    # 1. Database: SQLite's online backup copies a consistent snapshot, WAL included,
    #    while other connections keep reading and writing.
    src = sqlite3.connect(str(db_path), timeout=30)
    dst = sqlite3.connect(str(work / DB_NAME))
    try:
        src.backup(dst)
        # A single self-contained file: no -wal or -shm beside it.
        dst.execute("PRAGMA journal_mode=DELETE")
    finally:
        dst.close()
        src.close()
    if not _integrity_ok(work / DB_NAME):
        shutil.rmtree(work, ignore_errors=True)
        raise BackupError("The backup copy failed SQLite's integrity check.")

    # 2. Photos and register pages.
    for area in PHOTO_AREAS:
        src_dir = data_dir / area
        if src_dir.is_dir():
            shutil.copytree(src_dir, work / area, ignore=shutil.ignore_patterns("*.part"))

    # 3. Manifest.
    files = {
        p.relative_to(work).as_posix(): _sha256(p)
        for p in sorted(work.rglob("*"))
        if p.is_file()
    }
    manifest: dict[str, Any] = {
        "format": 1,
        "created_at": clock.iso_z(clock.now_utc()),
        "schema_revision": _revision(work / DB_NAME),
        "row_counts": _row_counts(work / DB_NAME),
        "files": files,
    }
    (work / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    work.rename(target)
    return target


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    """Check the manifest, every file hash and the database integrity. Returns the manifest."""
    backup_dir = Path(backup_dir)
    mf = backup_dir / MANIFEST
    if not mf.is_file():
        raise BackupError(f"{backup_dir} has no {MANIFEST}; it is not a Vaari backup.")
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    files: dict[str, str] = manifest.get("files", {})
    if DB_NAME not in files:
        raise BackupError("The manifest does not list the database.")
    on_disk = {
        p.relative_to(backup_dir).as_posix()
        for p in backup_dir.rglob("*")
        if p.is_file() and p.name != MANIFEST
    }
    missing = sorted(set(files) - on_disk)
    extra = sorted(on_disk - set(files))
    if missing:
        raise BackupError(f"Files listed in the manifest are missing: {missing[:5]}")
    if extra:
        raise BackupError(f"Files not in the manifest were found: {extra[:5]}")
    for rel, expected in files.items():
        if _sha256(backup_dir / rel) != expected:
            raise BackupError(f"{rel} does not match its SHA-256 in the manifest; the backup is damaged.")
    if not _integrity_ok(backup_dir / DB_NAME):
        raise BackupError("The backup database failed SQLite's integrity check.")
    return manifest


def restore_backup(backup_dir: Path, db_path: Path, data_dir: Path, force: bool = False) -> dict[str, Any]:
    """Replace the database and photos with a verified backup. Returns a summary."""
    backup_dir, db_path, data_dir = Path(backup_dir), Path(db_path), Path(data_dir)
    manifest = verify_backup(backup_dir)
    if db_path.exists() and not force:
        raise BackupError(
            f"A database already exists at {db_path}. Stop the server, then run restore again with --force. "
            "The current database and photos will be kept beside them as *.pre-restore-<time>."
        )

    stamp = _stamp()
    kept: list[str] = []
    for p in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        if p.exists():
            moved = p.with_name(f"{p.name}.pre-restore-{stamp}")
            p.rename(moved)
            kept.append(str(moved))
    for area in PHOTO_AREAS:
        cur = data_dir / area
        if cur.exists():
            moved = cur.with_name(f"{area}.pre-restore-{stamp}")
            cur.rename(moved)
            kept.append(str(moved))

    db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_dir / DB_NAME, db_path)
    for area in PHOTO_AREAS:
        if (backup_dir / area).is_dir():
            shutil.copytree(backup_dir / area, data_dir / area)

    # A backup from an older version is brought up to the current schema.
    from sqlalchemy import create_engine

    from app.migrate import ensure_schema

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        revision = ensure_schema(engine)
    finally:
        engine.dispose()

    return {
        "restored_from": str(backup_dir),
        "backup_created_at": manifest.get("created_at"),
        "schema_revision": revision,
        "row_counts": _row_counts(db_path),
        "kept_previous": kept,
    }


def prune_backups(out_root: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` backup folders. Returns what was deleted."""
    out_root = Path(out_root)
    if keep < 1 or not out_root.is_dir():
        return []
    backups = sorted(
        (p for p in out_root.iterdir() if p.is_dir() and p.name.startswith(BACKUP_PREFIX) and not p.name.endswith(".part")),
        key=lambda p: p.name,
    )
    doomed = backups[:-keep]
    for p in doomed:
        shutil.rmtree(p)
    return doomed
