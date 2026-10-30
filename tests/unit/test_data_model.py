"""Tests for data model, enums, acres helpers and event log (Step 02)."""

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect

from app.db import get_engine
from app.enums import from_x100, to_x100
from app.event_log import log_event
from app.models import EventLog
from app.schemas import RequestIn

EXPECTED_TABLES = {
    "village": {"id", "name", "lat", "lon"},
    "centre": {"id", "name", "phone", "lat", "lon", "is_home", "service_types"},
    "machine": {
        "id", "centre_id", "name", "type", "service_types", "capacity_acres_x100",
        "implement_width_m", "active_from", "active_to", "status", "link_token",
        "link_expires_at", "link_revoked_at",  # pilot v0.2 (A4)
    },
    "farmer": {
        "id", "phone", "name", "language", "consent_service", "consent_evidence",
        "consent_share", "consent_at", "consent_simulated",
    },
    "plot": {
        "id", "farmer_id", "village_name", "village_id", "pin_lat", "pin_lon",
        "geojson", "acres_x100", "centroid_lat", "centroid_lon", "location_source",
    },
    "intake_page": {
        "id", "centre_id", "image_path", "image_sha256", "image_delete_after",
        "reader", "prompt_version", "latency_ms", "status", "error", "created_at",
    },
    "register_draft": {
        "id", "intake_page_id", "row_no", "row_json", "confidence_json",
        "issues_json", "edited", "edited_fields_json", "skipped", "confirmed_at", "request_id",
    },
    "request": {
        "id", "centre_id", "farmer_id", "plot_id", "service_type", "source",
        "acres_x100", "harvest_date", "sow_by", "deadline_date", "deadline_overridden",
        "status", "reason_code", "reason", "next_action", "data_used_json",
        "nearest_alternative", "alternative_distance_km", "created_at", "updated_at",
    },
    "slot": {
        "id", "request_id", "machine_id", "service_date", "seq", "status",
        "link_token", "service_code", "est_distance_km", "notified_at",
        "started_at", "done_at", "not_served_reason", "not_served_note",
        "code_entered", "farmer_confirmed", "flags_json", "needs_review", "created_at",
    },
    "evidence": {
        "id", "slot_id", "kind", "server_time", "lat", "lon", "accuracy_m",
        "distance_to_plot_m", "plausible", "photo_path", "photo_sha256", "photo_bytes",
    },
    "service_record": {
        "id", "slot_id", "token", "outcome", "on_time", "record_hash",
        "hash_version", "generated_at",
        "token_expires_at", "token_revoked_at",  # pilot v0.2 (A4)
    },
    "message_log": {
        "id", "slot_id", "farmer_id", "channel", "template", "body", "status", "created_at",
    },
    "event_log": {
        "id", "actor", "entity", "entity_id", "event", "payload_json", "at",
    },
}


def test_every_table_and_column_matches_contract(temp_db):
    engine = get_engine()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table_name, expected_columns in EXPECTED_TABLES.items():
        assert table_name in existing_tables, f"Table {table_name} missing from database"
        actual_columns = {col["name"] for col in inspector.get_columns(table_name)}
        assert actual_columns == expected_columns, (
            f"Table {table_name} columns mismatch: extra={actual_columns - expected_columns}, "
            f"missing={expected_columns - actual_columns}"
        )


def test_C13_acres_exact_math():
    """Test C13: to_x100(2.4) + to_x100(3.6) == to_x100(6.0)."""
    assert to_x100(2.4) == 240
    assert to_x100(3.6) == 360
    assert to_x100(2.4) + to_x100(3.6) == to_x100(6.0)
    assert from_x100(to_x100(3.2)) == 3.2


def test_acres_round_trip():
    values = [0.25, 1.0, 3.2, 8.0, 15.75, 200.0]
    for val in values:
        assert from_x100(to_x100(val)) == val


def test_phone_validation_error_field():
    with pytest.raises(ValidationError) as exc_info:
        RequestIn(
            phone="12345",  # invalid
            village="Pind Kalan",
            acres=3.2,
            service_type="super_seeder",
            consent_service=True,
        )
    errors = exc_info.value.errors()
    assert errors[0]["loc"][-1] == "phone"


def test_acres_validation_error_field():
    with pytest.raises(ValidationError) as exc_info:
        RequestIn(
            phone="9876543210",
            village="Pind Kalan",
            acres=0.1,  # below 0.25
            service_type="super_seeder",
            consent_service=True,
        )
    errors = exc_info.value.errors()
    assert errors[0]["loc"][-1] == "acres"


def test_event_log_only_inserts(temp_db):
    session = temp_db()
    try:
        entry = log_event(
            session=session,
            actor="operator",
            entity="request",
            entity_id=1,
            event="created",
            payload={"source": "form"},
        )
        session.commit()

        loaded = session.query(EventLog).filter_by(id=entry.id).first()
        assert loaded is not None
        assert loaded.actor == "operator"
        assert loaded.entity == "request"
        assert loaded.event == "created"
        assert loaded.payload_json == {"source": "form"}
        assert loaded.at is not None

        # Verify event_log module has no update or delete functions
        import app.event_log as el_mod
        functions = [f for f in dir(el_mod) if not f.startswith("_")]
        assert "update_event" not in functions
        assert "delete_event" not in functions
    finally:
        session.close()
