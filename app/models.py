"""SQLAlchemy ORM models for Vaari (Contract Section 6)."""

import json

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
)

from app.db import Base


class JsonText(TypeDecorator):
    """Store JSON as Text in SQLite, return Python object."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, default=str)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(value)


class Village(Base):
    __tablename__ = "village"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)


class Centre(Base):
    __tablename__ = "centre"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    is_home = Column(Boolean, nullable=False, default=False)
    service_types = Column(JsonText, nullable=False, default=list)


class Machine(Base):
    __tablename__ = "machine"

    id = Column(Integer, primary_key=True, autoincrement=True)
    centre_id = Column(Integer, ForeignKey("centre.id"), nullable=False)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    service_types = Column(JsonText, nullable=False, default=list)
    capacity_acres_x100 = Column(Integer, nullable=False)
    implement_width_m = Column(Float, nullable=True)
    active_from = Column(Date, nullable=True)
    active_to = Column(Date, nullable=True)
    status = Column(String, nullable=False, default="active")
    link_token = Column(String, unique=True, nullable=False)
    # Pilot v0.2: driver links expire and can be turned off. Null expiry = no expiry (older rows).
    link_expires_at = Column(DateTime, nullable=True)
    link_revoked_at = Column(DateTime, nullable=True)


class Farmer(Base):
    __tablename__ = "farmer"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=True)
    language = Column(String, nullable=False, default="pa")
    consent_service = Column(Boolean, nullable=False)
    consent_evidence = Column(Boolean, nullable=False)
    consent_share = Column(Boolean, nullable=False)
    consent_at = Column(DateTime, nullable=False)
    consent_simulated = Column(Boolean, nullable=False, default=True)


class Plot(Base):
    __tablename__ = "plot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    farmer_id = Column(Integer, ForeignKey("farmer.id"), nullable=False)
    village_name = Column(String, nullable=False)
    village_id = Column(Integer, ForeignKey("village.id"), nullable=True)
    pin_lat = Column(Float, nullable=True)
    pin_lon = Column(Float, nullable=True)
    geojson = Column(Text, nullable=True)
    acres_x100 = Column(Integer, nullable=False)
    centroid_lat = Column(Float, nullable=True)
    centroid_lon = Column(Float, nullable=True)
    location_source = Column(String, nullable=False)


class IntakePage(Base):
    __tablename__ = "intake_page"

    id = Column(Integer, primary_key=True, autoincrement=True)
    centre_id = Column(Integer, ForeignKey("centre.id"), nullable=False)
    image_path = Column(String, nullable=False)
    image_sha256 = Column(String, nullable=False)
    image_delete_after = Column(DateTime, nullable=False)
    reader = Column(String, nullable=False)
    prompt_version = Column(String, nullable=False)
    latency_ms = Column(Integer, nullable=True)
    status = Column(String, nullable=False)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)


class RegisterDraft(Base):
    __tablename__ = "register_draft"

    id = Column(Integer, primary_key=True, autoincrement=True)
    intake_page_id = Column(Integer, ForeignKey("intake_page.id"), nullable=False)
    row_no = Column(Integer, nullable=False)
    row_json = Column(JsonText, nullable=False)
    confidence_json = Column(JsonText, nullable=False)
    issues_json = Column(JsonText, nullable=False)
    edited = Column(Boolean, nullable=False, default=False)
    edited_fields_json = Column(JsonText, nullable=False, default=dict)
    skipped = Column(Boolean, nullable=False, default=False)
    confirmed_at = Column(DateTime, nullable=True)
    request_id = Column(Integer, ForeignKey("request.id"), nullable=True)


class Request(Base):
    __tablename__ = "request"

    id = Column(Integer, primary_key=True, autoincrement=True)
    centre_id = Column(Integer, ForeignKey("centre.id"), nullable=False)
    farmer_id = Column(Integer, ForeignKey("farmer.id"), nullable=False)
    plot_id = Column(Integer, ForeignKey("plot.id"), nullable=False)
    service_type = Column(String, nullable=False)
    source = Column(String, nullable=False)
    acres_x100 = Column(Integer, nullable=False)
    harvest_date = Column(Date, nullable=True)
    sow_by = Column(Date, nullable=True)
    deadline_date = Column(Date, nullable=True, index=True)
    deadline_overridden = Column(Boolean, nullable=False, default=False)
    status = Column(String, nullable=False, index=True)
    reason_code = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    next_action = Column(String, nullable=True)
    data_used_json = Column(JsonText, nullable=True)
    nearest_alternative = Column(String, nullable=True)
    alternative_distance_km = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class Slot(Base):
    __tablename__ = "slot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey("request.id"), nullable=False)
    machine_id = Column(Integer, ForeignKey("machine.id"), nullable=False, index=True)
    service_date = Column(Date, nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    link_token = Column(String, unique=True, nullable=False)
    service_code = Column(String, nullable=False)
    est_distance_km = Column(Float, nullable=True)
    notified_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    done_at = Column(DateTime, nullable=True)
    not_served_reason = Column(String, nullable=True)
    not_served_note = Column(String, nullable=True)
    code_entered = Column(String, nullable=True)
    farmer_confirmed = Column(Boolean, nullable=True)
    flags_json = Column(JsonText, nullable=False, default=list)
    needs_review = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False)


class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slot_id = Column(Integer, ForeignKey("slot.id"), nullable=False)
    kind = Column(String, nullable=False)
    server_time = Column(DateTime, nullable=False)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    accuracy_m = Column(Float, nullable=True)
    distance_to_plot_m = Column(Float, nullable=True)
    plausible = Column(Boolean, nullable=True)
    photo_path = Column(String, nullable=True)
    photo_sha256 = Column(String, nullable=True)
    photo_bytes = Column(Integer, nullable=True)


class ServiceRecord(Base):
    __tablename__ = "service_record"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slot_id = Column(Integer, ForeignKey("slot.id"), unique=True, nullable=False)
    token = Column(String, unique=True, nullable=False)
    outcome = Column(String, nullable=False, default="COMPLETED")
    on_time = Column(Boolean, nullable=False)
    record_hash = Column(String, nullable=False)
    hash_version = Column(String, nullable=False, default="v1")
    generated_at = Column(DateTime, nullable=False)
    # Pilot v0.2: record links expire and can be turned off. Not part of the record hash.
    token_expires_at = Column(DateTime, nullable=True)
    token_revoked_at = Column(DateTime, nullable=True)


class MessageLog(Base):
    __tablename__ = "message_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slot_id = Column(Integer, ForeignKey("slot.id"), nullable=False)
    farmer_id = Column(Integer, ForeignKey("farmer.id"), nullable=False)
    channel = Column(String, nullable=False)
    template = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)


class EventLog(Base):
    __tablename__ = "event_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor = Column(String, nullable=False)
    entity = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=False)
    event = Column(String, nullable=False)
    payload_json = Column(JsonText, nullable=True)
    at = Column(DateTime, nullable=False)


class UserAccount(Base):
    """A person who signs in: an operator at the centre or an officer (pilot v0.2)."""

    __tablename__ = "user_account"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # operator | officer
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False)
    last_login_at = Column(DateTime, nullable=True)


class AuthSession(Base):
    """A signed-in session. Only a SHA-256 of the session id is stored (pilot v0.2)."""

    __tablename__ = "auth_session"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sid_sha256 = Column(String, unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("user_account.id"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
