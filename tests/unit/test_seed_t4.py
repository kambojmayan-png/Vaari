"""Test T4: seed counts invariant on different dates."""

import pytest

from app.models import Machine, Request, Slot
from app.seed.seed import reset_db


@pytest.mark.parametrize(
    "today_override",
    [
        "2026-10-19",  # Monday in October
        "2026-10-30",  # 30th of October
        "2027-01-01",  # 1st of January
    ],
)
def test_T4_seed_counts_and_demo_slot_on_any_date(monkeypatch, temp_db, today_override):
    monkeypatch.setenv("VAARI_TODAY", today_override)

    counts = reset_db()
    assert counts["total"] == 40
    assert counts["scheduled"] == 28
    assert counts["will_miss"] == 7
    assert counts["needs_info"] == 5

    # Check the demo request: Super Seeder 01, today, seq 1
    session = temp_db()
    try:
        demo_req = session.query(Request).filter_by(id=1).one()
        assert demo_req.status == "scheduled"

        demo_slot = session.query(Slot).filter_by(request_id=1).one()
        assert str(demo_slot.service_date) == today_override
        assert demo_slot.seq == 1

        machine = session.query(Machine).filter_by(id=demo_slot.machine_id).one()
        assert machine.name == "Super Seeder 01"
    finally:
        session.close()
