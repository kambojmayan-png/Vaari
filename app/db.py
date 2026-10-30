"""Database engine and session management for Vaari."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import settings

Base = declarative_base()

_engine = None
_SessionFactory = None


def get_sqlite_url(db_path: str) -> str:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def init_db(db_path: str | None = None):
    global _engine, _SessionFactory
    path = db_path if db_path is not None else settings.db_path
    db_url = get_sqlite_url(path)

    _engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    _SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _engine


def get_engine():
    global _engine
    if _engine is None:
        init_db()
    return _engine


def get_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        init_db()
    return _SessionFactory


def get_db() -> Generator[Session, None, None]:
    SessionFactory = get_session_factory()
    session: Session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


def override_db(engine, session_factory):
    """Used by tests to override the database engine and session factory."""
    global _engine, _SessionFactory
    _engine = engine
    _SessionFactory = session_factory
