"""Online backup and tested restore (pilot item B8)."""

import json
import sqlite3
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backup import BackupError, create_backup, prune_backups, restore_backup, verify_backup
from app.migrate import ensure_schema, head_revision
from app.seed.seed import seed_data


@pytest.fixture
def live(tmp_path, monkeypatch):
    """A seeded database in WAL mode plus a photo, like a running centre."""
    db = tmp_path / "live" / "vaari.sqlite"
    data = tmp_path / "live" / "data"
    db.parent.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.connect() as c:
        c.exec_driver_sql("PRAGMA journal_mode=WAL")
    ensure_schema(engine)
    with sessionmaker(bind=engine)() as s:
        seed_data(s)
    engine.dispose()
    (data / "photos").mkdir(parents=True)
    (data / "photos" / "1_start_aaaaaaaaaaaa.jpg").write_bytes(b"\xff\xd8\xffphoto-one")
    (data / "register_pages").mkdir()
    (data / "register_pages" / "register_bbbbbbbbbbbb.jpg").write_bytes(b"\xff\xd8\xffpage")
    return db, data, tmp_path / "backups"


def count(db: Path, table: str) -> int:
    con = sqlite3.connect(db)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


def test_backup_contains_db_photos_and_manifest(live):
    db, data, out = live
    b = create_backup(db, data, out)
    assert b.name.startswith("vaari-backup-") and b.is_dir()
    m = json.loads((b / "manifest.json").read_text())
    assert m["schema_revision"] == head_revision()
    assert m["row_counts"]["request"] == 40
    assert set(m["files"]) == {
        "vaari.sqlite",
        "photos/1_start_aaaaaaaaaaaa.jpg",
        "register_pages/register_bbbbbbbbbbbb.jpg",
    }
    verify_backup(b)


def test_backup_includes_uncheckpointed_wal_writes_and_runs_while_db_is_busy(live):
    db, data, out = live
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("UPDATE request SET status='cancelled' WHERE id=40")
    con.commit()
    assert Path(f"{db}-wal").stat().st_size > 0  # the change is only in the WAL

    reader = sqlite3.connect(db)
    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM request").fetchone()  # an open read transaction
    errors: list[Exception] = []

    def backup():
        try:
            backup.result = create_backup(db, data, out)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    t = threading.Thread(target=backup)
    t.start()
    t.join(30)
    reader.rollback()
    reader.close()
    con.close()
    assert not errors
    bcon = sqlite3.connect(backup.result / "vaari.sqlite")
    assert bcon.execute("SELECT status FROM request WHERE id=40").fetchone()[0] == "cancelled"
    bcon.close()


def test_restore_brings_back_data_and_photos_and_keeps_the_previous(live):
    db, data, out = live
    b = create_backup(db, data, out)

    con = sqlite3.connect(db)
    con.execute("DELETE FROM message_log")
    con.execute("DELETE FROM event_log")
    con.execute("DELETE FROM slot")
    con.execute("DELETE FROM request")
    con.commit()
    con.close()
    (data / "photos" / "1_start_aaaaaaaaaaaa.jpg").unlink()
    assert count(db, "request") == 0

    with pytest.raises(BackupError, match="--force"):
        restore_backup(b, db, data)
    summary = restore_backup(b, db, data, force=True)

    assert count(db, "request") == 40
    assert (data / "photos" / "1_start_aaaaaaaaaaaa.jpg").read_bytes() == b"\xff\xd8\xffphoto-one"
    assert summary["schema_revision"] == head_revision()
    kept = [Path(p) for p in summary["kept_previous"]]
    assert any(p.name.startswith("vaari.sqlite.pre-restore-") for p in kept)
    assert count(next(p for p in kept if p.name.startswith("vaari.sqlite.pre")), "request") == 0


def test_restore_into_an_empty_place(live, tmp_path):
    db, data, out = live
    b = create_backup(db, data, out)
    new_db = tmp_path / "fresh" / "vaari.sqlite"
    new_data = tmp_path / "fresh" / "data"
    restore_backup(b, new_db, new_data)
    assert count(new_db, "request") == 40
    assert (new_data / "register_pages" / "register_bbbbbbbbbbbb.jpg").exists()


def test_damaged_backup_is_refused_and_nothing_changes(live):
    db, data, out = live
    b = create_backup(db, data, out)
    photo = b / "photos" / "1_start_aaaaaaaaaaaa.jpg"
    photo.write_bytes(photo.read_bytes() + b"tampered")
    before = db.read_bytes()
    with pytest.raises(BackupError, match="SHA-256"):
        restore_backup(b, db, data, force=True)
    assert db.read_bytes() == before
    assert not list(db.parent.glob("*.pre-restore-*"))


def test_missing_or_extra_files_are_refused(live):
    db, data, out = live
    b = create_backup(db, data, out)
    (b / "extra.txt").write_text("x")
    with pytest.raises(BackupError, match="not in the manifest"):
        verify_backup(b)
    (b / "extra.txt").unlink()
    (b / "photos" / "1_start_aaaaaaaaaaaa.jpg").unlink()
    with pytest.raises(BackupError, match="missing"):
        verify_backup(b)


def test_not_a_backup_folder(tmp_path):
    with pytest.raises(BackupError, match="not a Vaari backup"):
        verify_backup(tmp_path)


def test_restore_of_an_older_schema_is_upgraded(live, tmp_path):
    from alembic import command

    from app.migrate import alembic_config

    db, data, out = live
    old = tmp_path / "old.sqlite"
    eng = create_engine(f"sqlite:///{old.as_posix()}")
    with eng.begin() as conn:
        command.upgrade(alembic_config(conn), "0001")
    eng.dispose()
    b = create_backup(old, data, out)
    target = tmp_path / "restored.sqlite"
    summary = restore_backup(b, target, tmp_path / "rdata")
    assert summary["schema_revision"] == head_revision()


def test_prune_keeps_the_newest(live, monkeypatch):
    db, data, out = live
    from datetime import timedelta

    from app import clock

    base = clock.now_utc()
    made = []
    for i in range(3):
        t = base + timedelta(minutes=i)
        monkeypatch.setattr(clock, "now_utc", lambda t=t: t)
        made.append(create_backup(db, data, out))
    removed = prune_backups(out, keep=1)
    assert removed == made[:2]
    assert [p for p in out.iterdir()] == [made[2]]


def test_backup_and_restore_commands(live, monkeypatch, capsys):
    import tasks

    db, data, out = live
    monkeypatch.setenv("VAARI_DB_PATH", str(db))
    monkeypatch.setenv("VAARI_DATA_DIR", str(data))
    assert tasks.task_backup(["--out", str(out)]) == 0
    b = next(out.iterdir())
    assert tasks.task_restore([str(b), "--verify-only"]) == 0
    assert tasks.task_restore([str(b)]) == 1  # refuses without --force
    assert tasks.task_restore([str(b), "--force"]) == 0
    text = capsys.readouterr().out
    assert "verified" in text and "Restore refused" in text and "Requests: 40" in text
