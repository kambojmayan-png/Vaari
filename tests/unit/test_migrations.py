"""Alembic migrations (pilot item B6)."""

import sqlite3

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401
from app.db import Base
from app.migrate import alembic_config, current_revision, ensure_schema, head_revision, is_at_head


@pytest.fixture
def engine(tmp_path):
    e = create_engine(f"sqlite:///{(tmp_path / 'm.sqlite').as_posix()}")
    yield e
    e.dispose()


def test_fresh_migration_matches_the_models(engine):
    ensure_schema(engine)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == [], f"Models and migrations differ; run python tasks.py db-revision. Diff: {diff}"
    assert current_revision(engine) == head_revision()
    assert is_at_head(engine)


def test_ensure_schema_is_idempotent(engine):
    ensure_schema(engine)
    ensure_schema(engine)
    assert current_revision(engine) == head_revision()


def test_downgrade_to_baseline_and_back(engine):
    ensure_schema(engine)
    with engine.begin() as conn:
        command.downgrade(alembic_config(conn), "0001")
    assert "user_account" not in inspect(engine).get_table_names()
    ensure_schema(engine)
    assert "user_account" in inspect(engine).get_table_names()


def _make_v010_database(engine) -> None:
    """A database as v0.1.0's create_all left it: baseline tables, no alembic_version."""
    with engine.begin() as conn:
        command.upgrade(alembic_config(conn), "0001")
        conn.exec_driver_sql("DROP TABLE alembic_version")
        conn.exec_driver_sql(
            "INSERT INTO centre (name, phone, lat, lon, is_home, service_types) "
            "VALUES ('Test Centre', '9000000001', 30.7, 76.7, 1, '[]')"
        )
        conn.exec_driver_sql(
            "INSERT INTO machine (centre_id, name, type, service_types, capacity_acres_x100, status, link_token) "
            "VALUES (1, 'SS 01', 'Super Seeder', '[\"super_seeder\"]', 800, 'active', 'tok-legacy')"
        )


def test_v010_database_is_stamped_and_upgraded_without_losing_data(engine):
    _make_v010_database(engine)
    assert current_revision(engine) is None
    ensure_schema(engine)
    assert current_revision(engine) == head_revision()
    cols = {c["name"] for c in inspect(engine).get_columns("machine")}
    assert {"link_expires_at", "link_revoked_at"} <= cols
    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT name, link_token, link_expires_at FROM machine").one()
    assert row == ("SS 01", "tok-legacy", None)  # old links keep working until rotated


def test_part_a_create_all_database_is_stamped_at_0002(engine):
    # A database made by create_all with the Part A models already has 0002's tables.
    Base.metadata.create_all(engine)
    ensure_schema(engine)
    assert current_revision(engine) == head_revision()


def test_app_startup_runs_migrations(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.db as dbmod
    from app.main import app

    db_file = tmp_path / "startup.sqlite"
    monkeypatch.setenv("VAARI_DB_PATH", str(db_file))
    old_engine, old_sf = dbmod._engine, dbmod._SessionFactory
    dbmod.init_db(str(db_file))
    try:
        with TestClient(app) as c:
            assert c.get("/api/health").json()["database"] == "connected"
        con = sqlite3.connect(db_file)
        (rev,) = con.execute("SELECT version_num FROM alembic_version").fetchone()
        con.close()
        assert rev == head_revision()
    finally:
        dbmod._engine.dispose()
        dbmod._engine, dbmod._SessionFactory = old_engine, old_sf


def test_no_create_all_at_startup():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "app" / "main.py").read_text(encoding="utf-8")
    assert "create_all" not in src
