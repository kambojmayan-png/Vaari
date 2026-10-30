"""Database migrations with Alembic (pilot item B6).

``ensure_schema()`` runs at start-up and in every command that opens the
database. It replaces ``Base.metadata.create_all``:

- an empty database is migrated from scratch to the newest revision;
- a database already under Alembic is upgraded to the newest revision;
- a database made by ``create_all`` before migrations existed (v0.1.0, or a
  Part A build) has no ``alembic_version`` table. It is *stamped* with the
  revision its tables match, then upgraded, so no data is lost.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine

from app.db import get_engine

ROOT_DIR = Path(__file__).resolve().parent.parent
BASELINE_REVISION = "0001"  # v0.1.0 tables
PILOT_ACCOUNTS_REVISION = "0002"  # Part A: accounts, sessions, link expiry


def alembic_config(connection: Connection | None = None) -> Config:
    cfg = Config(str(ROOT_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT_DIR / "migrations"))
    cfg.attributes["configure_logging"] = False
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine | None = None) -> str | None:
    engine = engine or get_engine()
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def _legacy_revision(conn: Connection) -> str | None:
    """For a database made by create_all: which revision do its tables match?"""
    insp = inspect(conn)
    tables = set(insp.get_table_names())
    if "alembic_version" in tables or "request" not in tables:
        return None
    machine_cols = {c["name"] for c in insp.get_columns("machine")}
    if "user_account" in tables and "link_expires_at" in machine_cols:
        return PILOT_ACCOUNTS_REVISION
    return BASELINE_REVISION


def ensure_schema(engine: Engine | None = None) -> str:
    """Bring the database to the newest revision. Returns that revision."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        legacy = _legacy_revision(conn)
        cfg = alembic_config(conn)
        if legacy is not None:
            command.stamp(cfg, legacy)
        command.upgrade(cfg, "head")
    return head_revision()


def is_at_head(engine: Engine | None = None) -> bool:
    try:
        return current_revision(engine) == head_revision()
    except Exception:
        return False
