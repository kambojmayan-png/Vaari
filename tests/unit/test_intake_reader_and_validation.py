"""Unit tests for Step 02: RegisterReader, MockRegisterReader, and validate_row."""

from datetime import date

import pytest

from app.intake.reader import (
    MockRegisterReader,
    ReaderUnavailable,
    get_reader,
)
from app.intake.validate import (
    FAILING_CONFIDENCE_CAP,
    LOW_CONFIDENCE_THRESHOLD,
    validate_row,
)

TODAY = date(2026, 10, 25)


def test_low_confidence_threshold_constant():
    assert LOW_CONFIDENCE_THRESHOLD == 0.8


def test_validate_row_valid_fields():
    fields = {
        "phone": "9876543210",
        "name": "Gurpreet Singh",
        "village": "Pind Kalan",
        "acres": 4.5,
        "service_type": "super_seeder",
        "harvest_date": "2026-10-20",
        "note": "Ready",
    }
    conf = {"phone": 0.95, "acres": 0.90}
    clean, issues = validate_row(fields, TODAY, confidence=conf)
    assert issues == []
    assert clean["phone"] == "9876543210"
    assert clean["acres"] == 4.5
    assert clean["service_type"] == "super_seeder"
    assert clean["harvest_date"] == "2026-10-20"
    assert conf["phone"] == 0.95


def test_validate_row_phone_rules_and_confidence_cap():
    # 7-digit phone fails, stays in clean_fields, adds issue, caps confidence at 0.3
    fields = {
        "phone": "9000000",
        "name": "Test",
        "village": "Pind Kalan",
        "acres": 3.0,
        "service_type": "super_seeder",
        "harvest_date": "2026-10-25",
    }
    conf = {"phone": 0.85}
    clean, issues = validate_row(fields, TODAY, confidence=conf)
    assert clean["phone"] == "9000000"  # never dropped
    assert any(i.startswith("phone:") for i in issues)
    assert conf["phone"] == FAILING_CONFIDENCE_CAP


def test_validate_row_acres_bounds_and_over_25_warning():
    # Sub 0.25 fails
    clean_low, issues_low = validate_row(
        {"phone": "9876543210", "village": "Pind", "acres": 0.1, "service_type": "baler"},
        TODAY,
    )
    assert clean_low["acres"] == 0.1
    assert any("acres:" in i for i in issues_low)

    # Over 25 acres adds warning "acres: unusually large, check the register" and caps confidence at 0.3
    conf = {"acres": 0.75}
    clean_40, issues_40 = validate_row(
        {"phone": "9876543210", "village": "Pind", "acres": 40.0, "service_type": "baler"},
        TODAY,
        confidence=conf,
    )
    assert clean_40["acres"] == 40.0
    assert "acres: unusually large, check the register" in issues_40
    assert conf["acres"] == FAILING_CONFIDENCE_CAP


@pytest.mark.parametrize(
    "raw_service,expected",
    [
        ("ਸੁਪਰ ਸੀਡਰ", "super_seeder"),
        ("super seeder", "super_seeder"),
        ("SS", "super_seeder"),
        ("ਹੈਪੀ ਸੀਡਰ", "happy_seeder"),
        ("happy seeder", "happy_seeder"),
        ("ਬੇਲਰ", "baler"),
        ("ਮਲਚਰ", "mulcher"),
    ],
)
def test_validate_row_punjabi_and_common_service_names(raw_service, expected):
    clean, issues = validate_row(
        {
            "phone": "9876543210",
            "village": "Pind Kalan",
            "acres": 3.0,
            "service_type": raw_service,
        },
        TODAY,
    )
    assert issues == []
    assert clean["service_type"] == expected


@pytest.mark.parametrize(
    "raw_date,expected_iso",
    [
        ("18/10", "2026-10-18"),
        ("18-10-2026", "2026-10-18"),
        ("2026-10-18", "2026-10-18"),
        ("22-10-26", "2026-10-22"),
        ("22/10/26", "2026-10-22"),
        (None, None),
    ],
)
def test_validate_row_date_formats(raw_date, expected_iso):
    clean, issues = validate_row(
        {
            "phone": "9876543210",
            "village": "Pind Kalan",
            "acres": 3.0,
            "service_type": "super_seeder",
            "harvest_date": raw_date,
        },
        TODAY,
    )
    assert issues == []
    assert clean["harvest_date"] == expected_iso


def test_validate_row_date_out_of_window_flagged():
    # More than 30 days before TODAY
    clean, issues = validate_row(
        {
            "phone": "9876543210",
            "village": "Pind Kalan",
            "acres": 3.0,
            "service_type": "super_seeder",
            "harvest_date": "2026-08-01",
        },
        TODAY,
    )
    assert any(i.startswith("harvest_date:") for i in issues)


def test_mock_reader_rejects_empty_bytes():
    reader = MockRegisterReader(today_override=TODAY)
    with pytest.raises(ReaderUnavailable):
        reader.read(b"")


def test_mock_reader_returns_6_row_fixture_with_expected_issues():
    reader = MockRegisterReader(today_override=TODAY)
    draft = reader.read(b"\xff\xd8\xffdummy-jpeg-bytes")

    assert draft.reader == "mock"
    assert draft.prompt_version == "v1"
    assert len(draft.rows) == 6

    # Check phones start with 9000000
    for r in draft.rows:
        assert str(r.fields["phone"]).startswith("9000000")

    # Row 2 had Punjabi service type "ਸੁਪਰ ਸੀਡਰ" and date "23/10" -> normalized cleanly
    row2 = draft.rows[1]
    assert row2.fields["service_type"] == "super_seeder"
    assert row2.fields["harvest_date"] == "2026-10-23"

    # Row 3 has 7-digit phone -> issue and confidence capped at 0.3
    row3 = draft.rows[2]
    assert row3.fields["phone"] == "9000000"
    assert any("phone:" in i for i in row3.issues)
    assert row3.confidence["phone"] == FAILING_CONFIDENCE_CAP

    # Row 4 has no harvest date -> allowed (optional), no blocking issue
    row4 = draft.rows[3]
    assert row4.fields["harvest_date"] is None
    assert row4.issues == []

    # Row 5 has acres 40.0 -> warning "acres: unusually large, check the register" and confidence capped at 0.3
    row5 = draft.rows[4]
    assert row5.fields["acres"] == 40.0
    assert "acres: unusually large, check the register" in row5.issues
    assert row5.confidence["acres"] == FAILING_CONFIDENCE_CAP

    # At least two low-confidence (< 0.8) cells across the draft
    low_conf_count = sum(
        1
        for r in draft.rows
        for val in r.confidence.values()
        if val < LOW_CONFIDENCE_THRESHOLD
    )
    assert low_conf_count >= 2


def test_get_reader_returns_mock_by_default():
    class DummySettings:
        reader = "mock"

    r = get_reader(DummySettings())
    assert isinstance(r, MockRegisterReader)
