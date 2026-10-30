"""Unit tests for app/clock.py and adherence to time rules (T1, T3)."""

import re
from datetime import date, datetime, timezone
from pathlib import Path

from app import clock


def test_T1_utc_to_ist_boundary(monkeypatch):
    """Test T1: with VAARI_TODAY unset and time at 2026-10-23T19:00Z, today() is 2026-10-24."""
    monkeypatch.delenv("VAARI_TODAY", raising=False)
    frozen_utc = datetime(2026, 10, 23, 19, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(clock, "now_utc", lambda: frozen_utc)

    assert clock.today() == date(2026, 10, 24)


def test_T3_clock_usage_ban_in_app():
    """Test T3: date.today(), datetime.now(), datetime.utcnow() must not appear outside app/clock.py."""
    app_dir = Path(__file__).parent.parent.parent / "app"
    forbidden_patterns = [
        re.compile(r"date\.today\s*\("),
        re.compile(r"datetime\.now\s*\("),
        re.compile(r"datetime\.utcnow\s*\("),
    ]

    violations = []
    for py_file in app_dir.rglob("*.py"):
        if py_file.name == "clock.py":
            continue
        content = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(content.splitlines(), start=1):
            for pattern in forbidden_patterns:
                if pattern.search(line):
                    violations.append(f"{py_file.name}:{line_no}: {line.strip()}")

    assert not violations, "Forbidden clock calls found outside app/clock.py:\n" + "\n".join(violations)


def test_vaari_today_override(monkeypatch):
    monkeypatch.setenv("VAARI_TODAY", "2026-11-15")
    assert clock.today() == date(2026, 11, 15)


def test_date_formatting():
    d = date(2026, 10, 23)
    assert clock.fmt_en(d) == "23 Oct"
    assert clock.fmt_pa(d) == "23 ਅਕਤੂਬਰ"


def test_iso_z_formatter():
    dt = datetime(2026, 10, 23, 5, 42, 10, tzinfo=timezone.utc)
    assert clock.iso_z(dt) == "2026-10-23T05:42:10Z"
