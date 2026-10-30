"""Pytest fixtures for Vaari tests."""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Ensure test passcode and settings
os.environ["VAARI_DEMO_PASSCODE"] = "test-passcode"
os.environ["VAARI_TZ"] = "Asia/Kolkata"
os.environ["VAARI_READER"] = "mock"
os.environ["VAARI_READER_PROBE"] = "false"

from app.db import get_db, override_db
from app.main import app


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Each test starts with empty rate-limit and lockout counters."""
    from app.ratelimit import limiter, lockout

    limiter.reset()
    lockout.reset()
    yield
    limiter.reset()
    lockout.reset()


def _sqlite_engine(path: str):
    engine = create_engine(f"sqlite:///{Path(path).as_posix()}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory):
    """One database built by the Alembic migrations (not create_all); each test gets a copy."""
    from app.migrate import ensure_schema

    path = tmp_path_factory.mktemp("template") / "template.sqlite"
    engine = _sqlite_engine(str(path))
    ensure_schema(engine)
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    engine.dispose()
    return path


@pytest.fixture
def temp_db(migrated_template):
    """Create a temporary SQLite database (a copy of the migrated template) for test isolation."""
    import shutil

    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        temp_path = tf.name
    shutil.copyfile(migrated_template, temp_path)

    db_url = f"sqlite:///{Path(temp_path).as_posix()}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    override_db(engine, SessionFactory)

    def _get_test_db():
        session = SessionFactory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_test_db

    yield SessionFactory

    app.dependency_overrides.pop(get_db, None)
    engine.dispose()
    try:
        Path(temp_path).unlink(missing_ok=True)
    except Exception:
        pass


@pytest.fixture
def client(temp_db):
    """TestClient configured with fresh temporary database."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    return {"X-Vaari-Passcode": "test-passcode"}
